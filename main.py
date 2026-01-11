from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Iterable, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

BASE_URL = "https://www.eet-china.com"
NEWS_PATH = "/news/"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


@dataclass
class NewsItem:
    title: str
    url: str
    date: Optional[str] = None


def extract_date(card: BeautifulSoup) -> Optional[str]:
    time_tag = card.find("time")
    if time_tag:
        value = time_tag.get("datetime") or time_tag.get_text(strip=True)
        if value:
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


def parse_news_items(html: str) -> List[NewsItem]:
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
    items: List[NewsItem] = []
    seen_urls: set[str] = set()

    for card in soup.select(", ".join(selectors)):
        link_tag = card.select_one("h4 a[href], a.m_title[href]")
        if not link_tag:
            link_candidates = [a for a in card.find_all("a", href=True) if a.get_text(strip=True)]
            link_tag = link_candidates[0] if link_candidates else None
        if not link_tag:
            continue
        title = link_tag.get_text(strip=True) or (link_tag.get("title") or "").strip()
        if not title:
            continue
        href = urljoin(BASE_URL, link_tag["href"])
        if href in seen_urls:
            continue
        seen_urls.add(href)
        items.append(NewsItem(title=title, url=href, date=extract_date(card)))

    return items


def scrape_news(
    pages: int = 1,
    delay: float = 0.5,
    *,
    timeout_ms: int = 20000,
    headless: bool = False,
    user_agent: str = DEFAULT_USER_AGENT,
    dump_html_path: Optional[str] = None,
) -> List[NewsItem]:
    all_items: List[NewsItem] = []

    with sync_playwright() as pw:
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
        page = context.new_page()

        for page_num in range(1, pages + 1):
            target_url = f"{BASE_URL}{NEWS_PATH}" if page_num == 1 else f"{BASE_URL}{NEWS_PATH}?page={page_num}"
            try:
                page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
            except PlaywrightTimeoutError:
                print(f"Page {page_num} timeout when fetching {target_url}")
                if page_num > 1:
                    break
                continue

            if delay > 0:
                page.wait_for_timeout(int(delay * 1000))

            html = page.content()
            if dump_html_path and page_num == 1:
                with open(dump_html_path, "w", encoding="utf-8") as fp:
                    fp.write(html)
            items = parse_news_items(html)
            if not items and page_num > 1:
                break
            all_items.extend(items)

        browser.close()

    return all_items


def format_items(items: Iterable[NewsItem]) -> str:
    lines = []
    for idx, item in enumerate(items, start=1):
        prefix = f"{idx:02d}. {item.title}"
        suffix = f" ({item.date})" if item.date else ""
        lines.append(f"{prefix}{suffix}\n    {item.url}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape EET-China news using Playwright")
    parser.add_argument("--pages", type=int, default=1, help="Number of pages to scrape")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds to wait after page load")
    parser.add_argument("--timeout-ms", type=int, default=20000, help="Navigation timeout in milliseconds")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode (default is headful)")
    parser.add_argument("--dump-html", help="Save first page HTML to a file for debugging")
    args = parser.parse_args()

    items = scrape_news(
        pages=max(args.pages, 1),
        delay=max(args.delay, 0.0),
        timeout_ms=max(args.timeout_ms, 1000),
        headless=bool(args.headless),
        dump_html_path=args.dump_html,
    )
    if not items:
        print("No news items found.")
        return
    print(format_items(items))


if __name__ == "__main__":
    main()
