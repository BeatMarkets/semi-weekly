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


@dataclass
class NewsContent:
    title: str
    url: str
    date: Optional[str] = None
    content: str = ""
    author: Optional[str] = None
    source: Optional[str] = None


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


def extract_article_content(html: str) -> tuple[Optional[str], Optional[str], str]:
    """
    Extract article title, author, and content from HTML.
    Returns: (title, author, content)
    """
    soup = BeautifulSoup(html, "html.parser")
    
    # Try to extract title
    title = None
    title_selectors = ["h1", "h1.m_title", "h1.title", "div.title h1", ".article-title"]
    for selector in title_selectors:
        title_tag = soup.select_one(selector)
        if title_tag:
            title = title_tag.get_text(strip=True)
            if title:
                break
    
    # Try to extract author
    author = None
    author_selectors = [
        "span.author",
        "span.m_auth",
        "p.author",
        "div.author",
        "span.m_newsauthor",
    ]
    for selector in author_selectors:
        author_tag = soup.select_one(selector)
        if author_tag:
            author = author_tag.get_text(strip=True)
            if author:
                break
    
    # Try to extract main content
    content = ""
    content_selectors = [
        "div.m_text",
        "div.article-content",
        "div.content",
        "article",
        "div.article-body",
        "div#content",
    ]
    
    for selector in content_selectors:
        content_tag = soup.select_one(selector)
        if content_tag:
            # Remove script and style tags
            for script_tag in content_tag.find_all(["script", "style"]):
                script_tag.decompose()
            
            # Extract text from paragraphs or divs
            text_parts = []
            for p in content_tag.find_all(["p", "div"]):
                text = p.get_text(strip=True)
                if text:
                    text_parts.append(text)
            
            if text_parts:
                content = "\n".join(text_parts)
                break
    
    # Fallback: if no content found, try to get all text from body
    if not content:
        body = soup.find("body")
        if body:
            for script_tag in body.find_all(["script", "style", "header", "footer", "nav"]):
                script_tag.decompose()
            content = body.get_text(strip=True)
    
    return title, author, content


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


def fetch_news_content(
    news_item: NewsItem,
    *,
    timeout_ms: int = 20000,
    headless: bool = False,
    user_agent: str = DEFAULT_USER_AGENT,
) -> Optional[NewsContent]:
    """
    Fetch detailed content from a single news article URL.
    Returns NewsContent with full article details, or None if fetch fails.
    """
    try:
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
            
            page.goto(news_item.url, wait_until="domcontentloaded", timeout=timeout_ms)
            html = page.content()
            browser.close()
            
            # Extract article details from HTML
            title, author, content = extract_article_content(html)
            
            # Use the original title if extraction fails
            final_title = title or news_item.title
            
            return NewsContent(
                title=final_title,
                url=news_item.url,
                date=news_item.date,
                content=content,
                author=author,
                source="EET-China",
            )
    except PlaywrightTimeoutError:
        print(f"Timeout fetching article: {news_item.url}")
        return None
    except Exception as e:
        print(f"Error fetching article {news_item.url}: {e}")
        return None


def fetch_news_contents(
    news_items: List[NewsItem],
    *,
    timeout_ms: int = 20000,
    headless: bool = False,
    user_agent: str = DEFAULT_USER_AGENT,
    delay: float = 0.5,
) -> List[NewsContent]:
    """
    Fetch detailed content for multiple news articles.
    """
    contents: List[NewsContent] = []
    total = len(news_items)
    
    for idx, item in enumerate(news_items, start=1):
        print(f"[{idx}/{total}] Fetching: {item.title[:50]}...")
        content = fetch_news_content(
            item,
            timeout_ms=timeout_ms,
            headless=headless,
            user_agent=user_agent,
        )
        if content:
            contents.append(content)
        
        # Add delay between requests
        if delay > 0 and idx < total:
            import time
            time.sleep(delay)
    
    return contents


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


def format_contents(contents: Iterable[NewsContent]) -> str:
    """Format NewsContent objects for display."""
    lines = []
    for idx, content in enumerate(contents, start=1):
        lines.append(f"\n{'='*80}")
        lines.append(f"{idx:02d}. {content.title}")
        if content.date:
            lines.append(f"发布时间: {content.date}")
        if content.author:
            lines.append(f"作者: {content.author}")
        lines.append(f"链接: {content.url}")
        lines.append(f"{'='*80}")
        lines.append(content.content)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape EET-China news using Playwright")
    parser.add_argument("--pages", type=int, default=1, help="Number of pages to scrape")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds to wait after page load")
    parser.add_argument("--timeout-ms", type=int, default=20000, help="Navigation timeout in milliseconds")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode (default is headful)")
    parser.add_argument("--dump-html", help="Save first page HTML to a file for debugging")
    parser.add_argument(
        "--fetch-content",
        action="store_true",
        help="Fetch full article content from each news item"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of articles to fetch content for (only with --fetch-content)"
    )
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
    
    # If --fetch-content flag is set, fetch full article content
    if args.fetch_content:
        # Limit the number of items if specified
        items_to_fetch = items[:args.limit] if args.limit else items
        contents = fetch_news_contents(
            items_to_fetch,
            timeout_ms=max(args.timeout_ms, 1000),
            headless=bool(args.headless),
            delay=max(args.delay, 0.0),
        )
        if contents:
            print(format_contents(contents))
        else:
            print("Failed to fetch article contents.")
    else:
        print(format_items(items))


if __name__ == "__main__":
    main()
