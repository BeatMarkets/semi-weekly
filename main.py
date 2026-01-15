from __future__ import annotations

import argparse
import json
import os
import random
import re
import sqlite3
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator, Optional
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
DEFAULT_DB_PATH = "data/semi_weekly.db"

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

REVIEW_STATUS_PENDING = "pending"
REVIEW_STATUS_REVIEWED = "reviewed"


def load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return

    try:
        with open(path, "r", encoding="utf-8") as fp:
            for raw_line in fp:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue

                if line.startswith("export "):
                    line = line[len("export ") :].strip()

                if "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if not key:
                    continue

                if (
                    (value.startswith('"') and value.endswith('"'))
                    or (value.startswith("'") and value.endswith("'"))
                ) and len(value) >= 2:
                    value = value[1:-1]

                os.environ.setdefault(key, value)
    except OSError:
        return


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


def create_context(browser: Any, *, user_agent: str) -> Any:
    return browser.new_context(
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


def create_browser_context(
    pw: Any, *, headless: bool, user_agent: str
) -> tuple[Any, Any]:
    browser = pw.chromium.launch(headless=headless, args=["--disable-http2"])
    context = create_context(browser, user_agent=user_agent)
    return browser, context


def scrape_list(
    context: Any,
    *,
    pages: int,
    timeout_ms: int,
    delay: float,
) -> list[NewsItem]:
    all_items: list[NewsItem] = []

    for page_num in range(1, pages + 1):
        page = context.new_page()
        target_url = (
            f"{BASE_URL}{NEWS_PATH}"
            if page_num == 1
            else f"{BASE_URL}{NEWS_PATH}index_{page_num}.html"
        )
        try:
            page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
        except PlaywrightTimeoutError:
            _eprint(f"List page timeout: page={page_num} url={target_url}")
            page.close()
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

    for item in items_list:
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


def ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)


def connect_db(db_path: str) -> sqlite3.Connection:
    ensure_parent_dir(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ensure_db_schema(conn)
    return conn


@contextmanager
def open_db(db_path: str) -> Iterator[sqlite3.Connection]:
    conn = connect_db(db_path)
    try:
        yield conn
    finally:
        conn.close()


def ensure_db_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS articles (
          id INTEGER PRIMARY KEY,
          source TEXT NOT NULL,
          url TEXT NOT NULL UNIQUE,
          title TEXT NOT NULL,
          date_raw TEXT,
          published_date TEXT,
          author TEXT,
          content TEXT,
          content_fetched_at TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS llm_results (
          article_id INTEGER PRIMARY KEY,
          model TEXT NOT NULL,
          base_url TEXT NOT NULL,
          category TEXT NOT NULL,
          summary_zh TEXT NOT NULL,
          raw_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS reviews (
          article_id INTEGER PRIMARY KEY,
          review_status TEXT NOT NULL,
          user_title TEXT,
          user_category TEXT,
          user_summary_zh TEXT,
          user_notes TEXT,
          reviewed_at TEXT,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_reviews_status ON reviews(review_status);
        CREATE INDEX IF NOT EXISTS idx_articles_pubdate ON articles(published_date);
        """
    )


_DATE_RE = re.compile(r"(\d{4})[\-/](\d{1,2})[\-/](\d{1,2})")
_DATE_ZH_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")


def normalize_published_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None

    text = str(value).strip()
    if not text:
        return None

    if len(text) >= 10 and text[4] in "-/" and text[7] in "-/":
        match = _DATE_RE.search(text[:10])
        if match:
            y, m, d = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
            return f"{y:04d}-{m:02d}-{d:02d}"

    match = _DATE_RE.search(text)
    if match:
        y, m, d = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        return f"{y:04d}-{m:02d}-{d:02d}"

    match = _DATE_ZH_RE.search(text)
    if match:
        y, m, d = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        return f"{y:04d}-{m:02d}-{d:02d}"

    return None


def get_pending_review_total(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(1) AS cnt FROM reviews WHERE review_status = ?",
        (REVIEW_STATUS_PENDING,),
    ).fetchone()
    return int(row["cnt"]) if row else 0


def upsert_article(
    conn: sqlite3.Connection,
    *,
    item: NewsItem,
    now: str,
) -> tuple[int, bool]:
    existing = conn.execute(
        "SELECT id FROM articles WHERE url = ?",
        (item.url,),
    ).fetchone()

    published_date = normalize_published_date(item.date)

    conn.execute(
        """
        INSERT INTO articles (
          source, url, title, date_raw, published_date, author, content, content_fetched_at,
          created_at, updated_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
          title = excluded.title,
          date_raw = excluded.date_raw,
          published_date = COALESCE(excluded.published_date, articles.published_date),
          updated_at = excluded.updated_at,
          last_seen_at = excluded.last_seen_at
        """,
        (
            "EET-China",
            item.url,
            item.title,
            item.date,
            published_date,
            now,
            now,
            now,
        ),
    )

    row = conn.execute("SELECT id FROM articles WHERE url = ?", (item.url,)).fetchone()
    if not row:
        raise RuntimeError(f"Failed to upsert article: url={item.url}")

    article_id = int(row["id"])
    conn.execute(
        """
        INSERT OR IGNORE INTO reviews (article_id, review_status, updated_at)
        VALUES (?, ?, ?)
        """,
        (article_id, REVIEW_STATUS_PENDING, now),
    )

    is_new = existing is None
    return article_id, is_new


def cmd_sync(
    *,
    db_path: str,
    pages: int,
    timeout_ms: int,
    delay: float,
    headless: bool,
) -> tuple[int, int, int]:
    now = _now_iso_utc()

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
        finally:
            context.close()
            browser.close()

    if not items:
        _eprint("No news items found.")
        return 0, 0, 0

    new_count = 0
    updated_count = 0
    with open_db(db_path) as conn:
        with conn:
            for item in items:
                _, is_new = upsert_article(conn, item=item, now=now)
                if is_new:
                    new_count += 1
                else:
                    updated_count += 1

        pending_total = get_pending_review_total(conn)

    _eprint(
        f"sync done: new={new_count} updated={updated_count} pending_total={pending_total}"
    )
    return new_count, updated_count, pending_total


def cmd_fetch(
    *,
    db_path: str,
    limit: int,
    timeout_ms: int,
    delay: float,
    headless: bool,
) -> int:
    with open_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, url, title, date_raw
            FROM articles
            WHERE content IS NULL OR content = ''
            ORDER BY COALESCE(published_date, '') DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    if not rows:
        _eprint("No articles need fetching.")
        return 0

    items = [
        NewsItem(
            title=str(row["title"]),
            url=str(row["url"]),
            date=str(row["date_raw"]) if row["date_raw"] is not None else None,
        )
        for row in rows
    ]

    details: list[NewsContent] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless, args=["--disable-http2"])
        try:
            for idx, item in enumerate(items, start=1):
                _eprint(f"[{idx}/{len(items)}] Fetching article: {item.title[:60]}")
                context = create_context(browser, user_agent=DEFAULT_USER_AGENT)
                try:
                    details.extend(
                        fetch_details(
                            context,
                            [item],
                            timeout_ms=timeout_ms,
                            delay=delay,
                        )
                    )
                finally:
                    context.close()
        finally:
            browser.close()

    if not details:
        _eprint("No article details fetched.")
        return 0

    now = _now_iso_utc()

    updated = 0
    with open_db(db_path) as conn:
        with conn:
            for content in details:
                conn.execute(
                    """
                    UPDATE articles
                    SET title = ?, author = ?, content = ?, content_fetched_at = ?, updated_at = ?
                    WHERE url = ?
                    """,
                    (
                        content.title,
                        content.author,
                        content.content,
                        now,
                        now,
                        content.url,
                    ),
                )
                updated += 1

    _eprint(f"fetch done: fetched={updated}")
    return updated


def cmd_llm(
    *,
    db_path: str,
    limit: int,
    model: str,
    max_retries: int,
) -> int:
    with open_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT a.id, a.title, a.url, a.date_raw, a.published_date, a.author, a.content
            FROM articles a
            LEFT JOIN llm_results l ON l.article_id = a.id
            WHERE l.article_id IS NULL
              AND a.content IS NOT NULL
              AND a.content != ''
            ORDER BY COALESCE(a.published_date, '') DESC, a.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    if not rows:
        _eprint("No articles need LLM processing.")
        return 0

    client = get_openai_client()
    llm_base_url = os.environ.get("OPENAI_BASE_URL") or DEFAULT_DASHSCOPE_BASE_URL

    now = _now_iso_utc()
    processed = 0

    with open_db(db_path) as conn:
        with conn:
            for idx, row in enumerate(rows, start=1):
                title = str(row["title"])
                _eprint(f"[{idx}/{len(rows)}] LLM processing: {title[:60]}")

                date_value = (
                    str(row["published_date"])
                    if row["published_date"]
                    else (str(row["date_raw"]) if row["date_raw"] else None)
                )
                content = NewsContent(
                    title=title,
                    url=str(row["url"]),
                    date=date_value,
                    author=str(row["author"]) if row["author"] else None,
                    content=str(row["content"]),
                    source="EET-China",
                )

                category, summary = classify_and_summarize(
                    client,
                    model=model,
                    content=content,
                    max_retries=max_retries,
                )

                raw_json = json.dumps(
                    {"category": category, "summary_zh": summary},
                    ensure_ascii=False,
                )

                conn.execute(
                    """
                    INSERT INTO llm_results (
                      article_id, model, base_url, category, summary_zh, raw_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(article_id) DO UPDATE SET
                      model = excluded.model,
                      base_url = excluded.base_url,
                      category = excluded.category,
                      summary_zh = excluded.summary_zh,
                      raw_json = excluded.raw_json,
                      created_at = excluded.created_at
                    """,
                    (
                        int(row["id"]),
                        model,
                        llm_base_url,
                        category,
                        summary,
                        raw_json,
                        now,
                    ),
                )
                conn.execute(
                    "UPDATE articles SET updated_at = ? WHERE id = ?",
                    (now, int(row["id"])),
                )
                processed += 1

    _eprint(f"llm done: processed={processed}")
    return processed


def cmd_run(
    *,
    db_path: str,
    pages: int,
    limit: int,
    model: str,
    timeout_ms: int,
    delay: float,
    max_retries: int,
    headless: bool,
) -> None:
    new_count, updated_count, _ = cmd_sync(
        db_path=db_path,
        pages=pages,
        timeout_ms=timeout_ms,
        delay=delay,
        headless=headless,
    )
    fetched = cmd_fetch(
        db_path=db_path,
        limit=limit,
        timeout_ms=timeout_ms,
        delay=delay,
        headless=headless,
    )
    llm_processed = cmd_llm(
        db_path=db_path,
        limit=limit,
        model=model,
        max_retries=max_retries,
    )

    with open_db(db_path) as conn:
        pending_total = get_pending_review_total(conn)

    print(
        "run summary: "
        f"new={new_count} updated={updated_count} "
        f"fetched={fetched} llm={llm_processed} pending_total={pending_total}"
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Scrape EET-China news into SQLite, then LLM classify & review. "
            "Env: OPENAI_API_KEY required for llm/run; OPENAI_BASE_URL optional."
        )
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="sync + fetch + llm")
    run_parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite DB path")
    run_parser.add_argument("--pages", type=int, default=1, help="Number of list pages")
    run_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Max articles for fetch/llm (sync is not limited)",
    )
    run_parser.add_argument("--model", default="qwen-plus", help="Model name")
    run_parser.add_argument(
        "--timeout-ms", type=int, default=20000, help="Navigation timeout"
    )
    run_parser.add_argument("--delay", type=float, default=0.5, help="Seconds to wait")
    run_parser.add_argument(
        "--max-retries", type=int, default=3, help="LLM retry count"
    )
    run_parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode (default is headful)",
    )

    return parser


def main() -> None:
    load_dotenv()

    parser = build_arg_parser()
    args = parser.parse_args()

    command = str(args.command)

    if command == "run":
        pages = max(int(args.pages), 1)
        limit = max(int(args.limit), 1)
        timeout_ms = max(int(args.timeout_ms), 1000)
        delay = max(float(args.delay), 0.0)
        max_retries = max(int(args.max_retries), 0)
        cmd_run(
            db_path=str(args.db),
            pages=pages,
            limit=limit,
            model=str(args.model),
            timeout_ms=timeout_ms,
            delay=delay,
            max_retries=max_retries,
            headless=bool(args.headless),
        )
        return

    raise RuntimeError(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
