from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from bs4.element import Tag
from openai import OpenAI
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

BASE_URL = "https://www.eet-china.com"
NEWS_PATH = "/news/"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

DEFAULT_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

CATEGORY_OPTIONS = (
    "eda/ip",
    "设计",
    "制造",
    "设备",
    "材料",
    "封装",
    "IDM",
    "其他",
)


@dataclass
class NewsItem:
    title: str
    url: str
    date: Optional[str] = None


@dataclass
class NewsContent:
    title: str
    url: str
    date: Optional[str] = None
    content: str = ""
    author: Optional[str] = None
    source: str = "EET-China"


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _eprint(message: str) -> None:
    print(message, file=sys.stderr)


def extract_date(card: Tag) -> Optional[str]:
    time_tag = card.find("time")
    if time_tag:
        value = time_tag.get("datetime") or time_tag.get_text(strip=True)
        if isinstance(value, str) and value:
            return value

    for selector in (
        "span.date",
        "div.date",
        "p.date",
        "span.time",
        "div.time",
        "span.m_newstime",
    ):
        tag = card.select_one(selector)
        if tag:
            text = tag.get_text(strip=True)
            if text:
                return text

    return None


def extract_article_content(html: str) -> tuple[Optional[str], Optional[str], str]:
    """Extract article title, author, and content from HTML."""
    soup = BeautifulSoup(html, "html.parser")

    title = None
    for selector in (
        "h1",
        "h1.m_title",
        "h1.title",
        "div.title h1",
        ".article-title",
    ):
        title_tag = soup.select_one(selector)
        if title_tag:
            title = title_tag.get_text(strip=True)
            if title:
                break

    author = None
    for selector in (
        "span.author",
        "span.m_auth",
        "p.author",
        "div.author",
        "span.m_newsauthor",
    ):
        author_tag = soup.select_one(selector)
        if author_tag:
            author = author_tag.get_text(strip=True)
            if author:
                break

    content = ""
    for selector in (
        "div.m_text",
        "div.article-content",
        "div.content",
        "article",
        "div.article-body",
        "div#content",
    ):
        content_tag = soup.select_one(selector)
        if not content_tag:
            continue

        for script_tag in content_tag.find_all(["script", "style"]):
            script_tag.decompose()

        text_parts: list[str] = []
        for p in content_tag.find_all(["p", "div"]):
            text = p.get_text(strip=True)
            if text:
                text_parts.append(text)

        if text_parts:
            content = "\n".join(text_parts)
            break

    if not content:
        body = soup.find("body")
        if body:
            for tag in body.find_all(["script", "style", "header", "footer", "nav"]):
                tag.decompose()
            content = body.get_text(strip=True)

    return title, author, content


def parse_news_items(html: str) -> list[NewsItem]:
    soup = BeautifulSoup(html, "html.parser")
    selectors = [
        "div.news-list li",
        "ul.news-list li",
        "div.article-list li",
        "div.news-item",
        "div.article-item",
        "ul.art-l-ul li",
        "li.art-l-li",
        "article",
    ]

    items: list[NewsItem] = []
    seen_urls: set[str] = set()

    for card in soup.select(", ".join(selectors)):
        link_tag = card.select_one("h4 a[href], a.m_title[href]")
        if not link_tag:
            link_candidates = [
                a for a in card.find_all("a", href=True) if a.get_text(strip=True)
            ]
            link_tag = link_candidates[0] if link_candidates else None
        if not link_tag:
            continue

        title_text = link_tag.get_text(strip=True)
        title_attr = link_tag.get("title")
        title_fallback = title_attr.strip() if isinstance(title_attr, str) else ""
        title = title_text or title_fallback
        if not title:
            continue

        href_attr = link_tag.get("href")
        href = href_attr if isinstance(href_attr, str) else ""
        if not href:
            continue

        full_url = urljoin(BASE_URL, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        items.append(NewsItem(title=title, url=full_url, date=extract_date(card)))

    return items


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.replace("\u00a0", " ").split())


def build_content_excerpt(content: str, *, max_chars: int = 2800) -> str:
    cleaned = content.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = "\n".join(line.strip() for line in cleaned.split("\n") if line.strip())
    cleaned = cleaned.strip()

    if not cleaned:
        return ""

    if len(cleaned) <= max_chars:
        return cleaned

    return cleaned[:max_chars]


def get_openai_client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing required env var: OPENAI_API_KEY")

    base_url = os.environ.get("OPENAI_BASE_URL") or DEFAULT_DASHSCOPE_BASE_URL
    return OpenAI(api_key=api_key, base_url=base_url)


def build_llm_messages(
    *,
    title: str,
    url: str,
    date: Optional[str],
    author: Optional[str],
    content_excerpt: str,
) -> list[dict[str, str]]:
    system = (
        "你是一个严谨的中文新闻分析助手。"
        "你的任务是对半导体相关新闻做产业链单标签分类，并做客观概括。"
        "输出必须是严格的 JSON，且只能输出 JSON；不要输出 Markdown，不要解释。"
        "category 必须是以下之一：eda/ip, 设计, 制造, 设备, 材料, 封装, IDM, 其他（必须单选）。"
        "summary_zh 为中文客观概括，优先一句话，允许 1-3 句；不夸张、不推测、不带主观评价。"
    )

    rules = (
        "分类说明：\n"
        "- eda/ip：EDA 软件、IP 授权、仿真验证、设计工具链、PDK 等\n"
        "- 设计：芯片/SoC/架构/方案/设计公司动态（不含 EDA/IP）\n"
        "- 制造：晶圆制造、制程节点、良率、产能、代工厂/工厂运营\n"
        "- 设备：光刻/刻蚀/沉积/量测/清洗等半导体设备及供应商\n"
        "- 材料：硅片、光刻胶、靶材、气体、化学品等上游材料\n"
        "- 封装：封装测试、先进封装（2.5D/3D/Chiplet/SiP 等）、OSAT\n"
        "- IDM：同时覆盖设计与制造的一体化厂商相关主事件\n"
        "- 其他：政策/市场/应用/人才等不清晰落在以上环节的内容\n"
        "若涉及多个环节，选择新闻主语与主要事件对应的那一类（只能单选）。\n"
        '输出 JSON schema（示例）：{"category":"设备","summary_zh":"..."}'
    )

    payload: dict[str, Any] = {
        "title": _normalize_whitespace(title),
        "url": url,
        "date": date,
        "author": _normalize_whitespace(author) if author else None,
        "content_excerpt": content_excerpt,
    }

    user = f"{rules}\n\n新闻内容（JSON）：\n{json.dumps(payload, ensure_ascii=False)}"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def parse_llm_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()

    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped.replace("json\n", "", 1).strip()

    first = stripped.find("{")
    last = stripped.rfind("}")
    if first == -1 or last == -1 or last <= first:
        raise ValueError("No JSON object found")

    candidate = stripped[first : last + 1]
    return json.loads(candidate)


def normalize_and_validate_llm_result(obj: dict[str, Any]) -> tuple[str, str]:
    category = str(obj.get("category", "")).strip()
    summary = str(obj.get("summary_zh", "")).strip()

    if category not in CATEGORY_OPTIONS:
        raise ValueError(f"Invalid category: {category}")

    summary = _normalize_whitespace(summary)
    if not summary:
        raise ValueError("Empty summary_zh")

    terminators = "。！？"
    count = 0
    for idx, ch in enumerate(summary):
        if ch in terminators:
            count += 1
            if count >= 3:
                summary = summary[: idx + 1].strip()
                break

    return category, summary


def chat_completion_with_retries(
    client: OpenAI,
    *,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_retries: int,
) -> str:
    last_error: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature,
            )
            return completion.choices[0].message.content or ""
        except Exception as e:  # noqa: BLE001
            last_error = e
            if attempt >= max_retries:
                break

            backoff = min(8.0, (2**attempt)) + random.random() * 0.2
            _eprint(f"LLM call failed (attempt {attempt + 1}/{max_retries + 1}): {e}")
            time.sleep(backoff)

    raise RuntimeError(f"LLM call failed after retries: {last_error}")


def classify_and_summarize(
    client: OpenAI,
    *,
    model: str,
    content: NewsContent,
    max_retries: int,
) -> tuple[str, str]:
    excerpt = build_content_excerpt(content.content)
    messages = build_llm_messages(
        title=content.title,
        url=content.url,
        date=content.date,
        author=content.author,
        content_excerpt=excerpt,
    )

    raw = chat_completion_with_retries(
        client,
        model=model,
        messages=messages,
        temperature=0.2,
        max_retries=max_retries,
    )

    try:
        obj = parse_llm_json_object(raw)
        return normalize_and_validate_llm_result(obj)
    except Exception:
        repair_messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "你是一个 JSON 修复器。只输出严格 JSON；不要输出任何额外文字。"
                    "输出必须包含且仅包含 category 与 summary_zh 两个字段。"
                    "category 只能是：eda/ip, 设计, 制造, 设备, 材料, 封装, IDM, 其他。"
                ),
            },
            {
                "role": "user",
                "content": f"请把下面内容修复为合法 JSON：\n{raw}",
            },
        ]

        repaired = chat_completion_with_retries(
            client,
            model=model,
            messages=repair_messages,
            temperature=0.0,
            max_retries=max_retries,
        )
        obj = parse_llm_json_object(repaired)
        return normalize_and_validate_llm_result(obj)


def create_browser_context(
    pw: Any, *, headless: bool, user_agent: str
) -> tuple[Any, Any]:
    browser = pw.chromium.launch(headless=headless, args=["--disable-http2"])
    context = browser.new_context(
        user_agent=user_agent,
        locale="zh-CN",
        viewport={"width": 1280, "height": 720},
        ignore_https_errors=True,
        extra_http_headers={
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Cache-Control": "no-cache",
        },
    )
    return browser, context


def scrape_list(
    context: Any,
    *,
    pages: int,
    timeout_ms: int,
    delay: float,
) -> list[NewsItem]:
    page = context.new_page()
    all_items: list[NewsItem] = []

    for page_num in range(1, pages + 1):
        target_url = (
            f"{BASE_URL}{NEWS_PATH}"
            if page_num == 1
            else f"{BASE_URL}{NEWS_PATH}?page={page_num}"
        )
        try:
            page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
        except PlaywrightTimeoutError:
            _eprint(f"List page timeout: page={page_num} url={target_url}")
            if page_num > 1:
                break
            continue

        if delay > 0:
            page.wait_for_timeout(int(delay * 1000))

        html = page.content()
        items = parse_news_items(html)
        if not items and page_num > 1:
            break
        all_items.extend(items)

    page.close()
    return all_items


def fetch_details(
    context: Any,
    items: Iterable[NewsItem],
    *,
    timeout_ms: int,
    delay: float,
) -> list[NewsContent]:
    contents: list[NewsContent] = []
    items_list = list(items)

    for idx, item in enumerate(items_list, start=1):
        _eprint(f"[{idx}/{len(items_list)}] Fetching article: {item.title[:60]}")

        page = context.new_page()
        try:
            page.goto(item.url, wait_until="domcontentloaded", timeout=timeout_ms)
            if delay > 0:
                page.wait_for_timeout(int(delay * 1000))

            html = page.content()
            title, author, content_text = extract_article_content(html)
            contents.append(
                NewsContent(
                    title=title or item.title,
                    url=item.url,
                    date=item.date,
                    author=author,
                    content=content_text,
                    source="EET-China",
                )
            )
        except PlaywrightTimeoutError:
            _eprint(f"Timeout fetching article: {item.url}")
        except Exception as e:  # noqa: BLE001
            _eprint(f"Error fetching article: {item.url} err={e}")
        finally:
            page.close()

    return contents


def load_processed_urls(out_path: str) -> set[str]:
    if not os.path.exists(out_path):
        return set()

    processed: set[str] = set()
    with open(out_path, "r", encoding="utf-8") as fp:
        for line_no, line in enumerate(fp, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError:
                _eprint(f"Skipping invalid JSONL line: {out_path}:{line_no}")
                continue

            url = record.get("url") if isinstance(record, dict) else None
            if isinstance(url, str) and url:
                processed.add(url)

    return processed


def _jsonl_needs_leading_newline(out_path: str) -> bool:
    try:
        with open(out_path, "rb") as fp:
            fp.seek(-1, os.SEEK_END)
            return fp.read(1) != b"\n"
    except OSError:
        return False


def write_jsonl(records: Iterable[dict[str, Any]], out_path: str) -> int:
    count = 0
    with open(out_path, "a", encoding="utf-8") as fp:
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            if _jsonl_needs_leading_newline(out_path):
                fp.write("\n")

        for record in records:
            fp.write(json.dumps(record, ensure_ascii=False))
            fp.write("\n")
            count += 1

    return count


def run_pipeline(
    *,
    pages: int,
    limit: int,
    out_path: str,
    model: str,
    timeout_ms: int,
    delay: float,
    max_retries: int,
    headless: bool,
) -> int:
    processed_urls = load_processed_urls(out_path)
    if processed_urls:
        _eprint(f"Loaded {len(processed_urls)} processed URLs from {out_path}")

    with sync_playwright() as pw:
        browser, context = create_browser_context(
            pw,
            headless=headless,
            user_agent=DEFAULT_USER_AGENT,
        )

        try:
            items = scrape_list(
                context, pages=pages, timeout_ms=timeout_ms, delay=delay
            )
            if not items:
                _eprint("No news items found.")
                return 0

            new_items = [item for item in items if item.url not in processed_urls]
            skipped = len(items) - len(new_items)
            if skipped > 0:
                _eprint(f"Skipping {skipped} already-processed articles")

            new_items = new_items[:limit]
            if not new_items:
                _eprint("No new items to process (all already processed).")
                return 0

            details = fetch_details(
                context,
                new_items,
                timeout_ms=timeout_ms,
                delay=delay,
            )

        finally:
            context.close()
            browser.close()

    if not details:
        _eprint("No article details fetched.")
        return 0

    client = get_openai_client()

    def records() -> Iterable[dict[str, Any]]:
        llm_base_url = os.environ.get("OPENAI_BASE_URL") or DEFAULT_DASHSCOPE_BASE_URL
        for idx, content in enumerate(details, start=1):
            _eprint(f"[{idx}/{len(details)}] LLM processing: {content.title[:60]}")
            category, summary = classify_and_summarize(
                client,
                model=model,
                content=content,
                max_retries=max_retries,
            )
            yield {
                **asdict(content),
                "category": category,
                "summary_zh": summary,
                "model": model,
                "created_at": _now_iso_utc(),
                "llm_base_url": llm_base_url,
            }

    return write_jsonl(records(), out_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Scrape EET-China news then classify & summarize with Qwen (JSONL). "
            "Env: OPENAI_API_KEY required; OPENAI_BASE_URL optional (defaults to DashScope)."
        )
    )

    parser.add_argument("--pages", type=int, default=1, help="Number of list pages")
    parser.add_argument("--limit", type=int, default=20, help="Max articles to process")
    parser.add_argument("--out", default="out.jsonl", help="Output JSONL path")
    parser.add_argument(
        "--model", default="qwen-plus", help="Model name, e.g. qwen-plus"
    )
    parser.add_argument(
        "--timeout-ms", type=int, default=20000, help="Navigation timeout"
    )
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds to wait")
    parser.add_argument("--max-retries", type=int, default=3, help="LLM retry count")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode (default is headful)",
    )

    args = parser.parse_args()

    pages = max(int(args.pages), 1)
    limit = max(int(args.limit), 1)
    timeout_ms = max(int(args.timeout_ms), 1000)
    delay = max(float(args.delay), 0.0)
    max_retries = max(int(args.max_retries), 0)

    try:
        total = run_pipeline(
            pages=pages,
            limit=limit,
            out_path=str(args.out),
            model=str(args.model),
            timeout_ms=timeout_ms,
            delay=delay,
            max_retries=max_retries,
            headless=bool(args.headless),
        )
    except RuntimeError as e:
        _eprint(str(e))
        sys.exit(2)

    print(f"Appended {total} records to {args.out}")


if __name__ == "__main__":
    main()
