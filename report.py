from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import date
from html import escape as html_escape
from typing import Any, Iterable, Optional

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


def _eprint(message: str) -> None:
    print(message, file=sys.stderr)


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.replace("\u00a0", " ").split())


def _parse_iso_date(value: Any) -> Optional[date]:
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        text = text[:10]

    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


_ZH_DIGITS = {
    0: "零",
    1: "一",
    2: "二",
    3: "三",
    4: "四",
    5: "五",
    6: "六",
    7: "七",
    8: "八",
    9: "九",
}


def _to_zh_number(value: int) -> str:
    if value < 0 or value > 99:
        raise ValueError(f"Unsupported number: {value}")

    if value < 10:
        return _ZH_DIGITS[value]

    tens, ones = divmod(value, 10)
    if tens == 1:
        prefix = "十"
    else:
        prefix = f"{_ZH_DIGITS[tens]}十"

    if ones == 0:
        return prefix

    return f"{prefix}{_ZH_DIGITS[ones]}"


def _format_week_badge(week: int) -> str:
    return f"W{week:02d}"


def _format_week_label_zh(week: int) -> str:
    return f"第{_to_zh_number(week)}周"


def _category_display_name(category: str) -> str:
    if category == "eda/ip":
        return "EDA/IP"
    return category


def read_jsonl(path: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as fp:
        for line_no, line in enumerate(fp, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as e:
                _eprint(f"Invalid JSONL line: {path}:{line_no} err={e}")
                continue

            if isinstance(obj, dict):
                records.append(obj)
            else:
                _eprint(f"Invalid JSONL line (not object): {path}:{line_no}")

    return records


def read_db_records(path: str) -> list[dict[str, Any]]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    rows = conn.execute(
        """
        SELECT
          a.id AS article_id,
          a.published_date AS date,
          a.title AS title,
          COALESCE(r.user_category, l.category, '其他') AS category,
          COALESCE(r.user_summary_zh, l.summary_zh) AS summary_zh,
          a.url AS url
        FROM reviews r
        JOIN articles a ON a.id = r.article_id
        LEFT JOIN llm_results l ON l.article_id = a.id
        WHERE r.review_status = 'reviewed'
          AND a.published_date IS NOT NULL
          AND a.published_date != ''
          AND COALESCE(r.user_summary_zh, l.summary_zh) IS NOT NULL
          AND COALESCE(r.user_summary_zh, l.summary_zh) != ''
        """
    ).fetchall()
    conn.close()

    records: list[dict[str, Any]] = []
    for row in rows:
        records.append(
            {
                "article_id": row["article_id"],
                "date": row["date"],
                "title": row["title"],
                "category": row["category"],
                "summary_zh": row["summary_zh"],
                "url": row["url"],
            }
        )
    return records


def _normalize_report_record(
    obj: dict[str, Any], *, year: int
) -> Optional[dict[str, Any]]:
    parsed_date = _parse_iso_date(obj.get("date"))
    if not parsed_date or parsed_date.year != year:
        return None

    summary_raw = obj.get("summary_zh")
    if not isinstance(summary_raw, str) or not summary_raw.strip():
        return None

    summary = _normalize_whitespace(summary_raw)

    url_raw = obj.get("url")
    url = url_raw.strip() if isinstance(url_raw, str) else ""

    category_raw = obj.get("category")
    category = str(category_raw).strip() if category_raw is not None else ""
    if category not in CATEGORY_OPTIONS:
        category = "其他"

    week = int(parsed_date.isocalendar().week)
    article_id_raw = obj.get("article_id")
    article_id = int(article_id_raw) if isinstance(article_id_raw, int) else None

    title_raw = obj.get("title")
    title = _normalize_whitespace(title_raw) if isinstance(title_raw, str) else ""

    return {
        "article_id": article_id,
        "category": category,
        "week": week,
        "date": parsed_date,
        "summary": summary,
        "title": title,
        "url": url,
    }


def build_weekly_report_index(
    records: Iterable[dict[str, Any]], *, year: int
) -> tuple[dict[str, dict[int, list[dict[str, Any]]]], int]:
    grouped: dict[str, dict[int, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    kept = 0

    for record in records:
        normalized = _normalize_report_record(record, year=year)
        if not normalized:
            continue
        grouped[normalized["category"]][normalized["week"]].append(normalized)
        kept += 1

    return grouped, kept


def build_related_map(*, db_path: str, year: int) -> dict[int, list[dict[str, Any]]]:
    start = f"{year:04d}-01-01"
    end = f"{year + 1:04d}-01-01"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    rows = conn.execute(
        """
        SELECT
          al.from_article_id AS from_id,
          a_to.id AS to_id,
          a_to.url AS url,
          a_to.title AS title,
          a_to.published_date AS date,
          COALESCE(r.user_summary_zh, l.summary_zh) AS summary_zh
        FROM article_links al
        JOIN articles a_from ON a_from.id = al.from_article_id
        JOIN articles a_to ON a_to.id = al.to_article_id
        LEFT JOIN reviews r ON r.article_id = a_to.id
        LEFT JOIN llm_results l ON l.article_id = a_to.id
        WHERE a_from.published_date >= ? AND a_from.published_date < ?
        ORDER BY a_to.published_date DESC, a_to.id DESC
        """,
        (start, end),
    ).fetchall()
    conn.close()

    related_map: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        from_id = row["from_id"]
        if not isinstance(from_id, int):
            continue

        summary_raw = row["summary_zh"]
        summary = (
            _normalize_whitespace(summary_raw) if isinstance(summary_raw, str) else ""
        )

        title_raw = row["title"]
        title = _normalize_whitespace(title_raw) if isinstance(title_raw, str) else ""

        if not summary and not title:
            continue

        parsed_date = _parse_iso_date(row["date"])
        week = int(parsed_date.isocalendar().week) if parsed_date else None
        related_map[from_id].append(
            {
                "article_id": row["to_id"],
                "url": row["url"],
                "date": row["date"],
                "week": week,
                "summary": summary,
                "title": title,
            }
        )

    return related_map


def render_weekly_report_html(
    grouped: dict[str, dict[int, list[dict[str, Any]]]],
    *,
    year: int,
    total: int,
    related_map: Optional[dict[int, list[dict[str, Any]]]] = None,
) -> str:
    title = f"{year} 半导体产业周报"
    subtitle = "按产业链分类 · 按全年周汇总"

    css = """
:root {
  --bg: #f6f7fb;
  --card: #ffffff;
  --text: #111827;
  --muted: #6b7280;
  --border: #e5e7eb;
  --shadow: 0 10px 25px rgba(0,0,0,0.06);
  --blue: #2563eb;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
               "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", Arial;
  color: var(--text);
  background: var(--bg);
}
.container { max-width: 1120px; margin: 0 auto; padding: 32px 18px 64px; }
.header h1 { margin: 0; font-size: 40px; letter-spacing: 0.5px; }
.header p { margin: 10px 0 0; color: var(--muted); font-size: 14px; }
.grid { display: grid; grid-template-columns: 1fr; gap: 18px; margin-top: 28px; }
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px;
  box-shadow: var(--shadow);
  overflow: hidden;
}
.card .card-title {
  padding: 18px 18px;
  font-size: 26px;
  font-weight: 700;
  border-bottom: 1px solid var(--border);
}
.section { padding: 18px 18px 10px; }
.week { display: flex; align-items: center; gap: 12px; margin: 14px 0 10px; }
.week .badge {
  background: var(--blue);
  color: white;
  font-weight: 700;
  border-radius: 10px;
  padding: 8px 12px;
  min-width: 54px;
  text-align: center;
}
.week .label { color: var(--muted); font-weight: 600; }
.items { margin: 0; padding: 0 0 8px 0; list-style: none; }
.items li { padding: 10px 0; border-bottom: 1px solid #f0f2f6; }
.items li:last-child { border-bottom: none; }
.items a {
  color: var(--text);
  text-decoration: none;
  display: block;
  line-height: 1.55;
}
.items a:hover { color: var(--text); text-decoration: none; }
.related-list {
  margin: 8px 0 0 14px;
  padding-left: 12px;
  border-left: 2px solid #eef1f6;
  color: var(--muted);
  font-size: 13px;
  display: grid;
  gap: 6px;
}
.related-item {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  line-height: 1.4;
}
.related-badge {
  font-weight: 700;
  color: var(--muted);
  min-width: 36px;
}
.footer { margin-top: 22px; color: var(--muted); font-size: 12px; }
"""

    parts: list[str] = []
    parts.append("<!doctype html>")
    parts.append('<html lang="zh-CN">')
    parts.append("<head>")
    parts.append('<meta charset="utf-8" />')
    parts.append(
        '<meta name="viewport" content="width=device-width, initial-scale=1" />'
    )
    parts.append(f"<title>{html_escape(title)}</title>")
    parts.append(f"<style>{css}</style>")
    parts.append("</head>")
    parts.append("<body>")
    parts.append('<div class="container">')
    parts.append('<div class="header">')
    parts.append(f"<h1>{html_escape(title)}</h1>")
    parts.append(f"<p>{html_escape(subtitle)} · 共 {total} 条摘要</p>")
    parts.append("</div>")
    parts.append('<div class="grid">')

    for category in CATEGORY_OPTIONS:
        weeks = grouped.get(category)
        if not weeks:
            continue

        parts.append('<section class="card">')
        parts.append(
            f'<div class="card-title">{html_escape(_category_display_name(category))}</div>'
        )
        parts.append('<div class="section">')

        for week in sorted(weeks.keys(), reverse=True):
            items = list(weeks[week])
            items.sort(key=lambda item: item["date"], reverse=True)

            parts.append('<div class="week">')
            parts.append(f'<div class="badge">{_format_week_badge(week)}</div>')
            parts.append(
                f'<div class="label">{html_escape(_format_week_label_zh(week))}</div>'
            )
            parts.append("</div>")
            parts.append('<ul class="items">')

            for item in items:
                summary = html_escape(str(item.get("summary", "")))
                url = str(item.get("url", "")).strip()
                article_id = item.get("article_id")
                if url:
                    safe_url = html_escape(url)
                    parts.append(f'<li><a href="{safe_url}">{summary}</a>')
                else:
                    parts.append(f"<li>{summary}")

                if (
                    related_map
                    and isinstance(article_id, int)
                    and related_map.get(article_id)
                ):
                    parts.append('<div class="related-list">')
                    for related in related_map[article_id]:
                        related_summary = html_escape(
                            str(related.get("summary") or related.get("title") or "")
                        )
                        related_url = str(related.get("url", "")).strip()
                        week_value = related.get("week")
                        badge = (
                            _format_week_badge(int(week_value))
                            if isinstance(week_value, int)
                            else "W??"
                        )
                        parts.append('<div class="related-item">')
                        parts.append(
                            f'<div class="related-badge">{html_escape(badge)}</div>'
                        )
                        if related_url:
                            safe_related_url = html_escape(related_url)
                            parts.append(
                                f'<a href="{safe_related_url}">{related_summary}</a>'
                            )
                        else:
                            parts.append(related_summary)
                        parts.append("</div>")
                    parts.append("</div>")

                parts.append("</li>")

            parts.append("</ul>")

        parts.append("</div>")
        parts.append("</section>")

    parts.append("</div>")
    parts.append('<div class="footer">Generated from SQLite/JSONL · Static HTML</div>')
    parts.append("</div>")
    parts.append("</body>")
    parts.append("</html>")

    return "\n".join(parts)


def generate_weekly_report(*, jsonl_path: str, html_path: str, year: int) -> int:
    records = read_jsonl(jsonl_path)
    grouped, total = build_weekly_report_index(records, year=year)
    html = render_weekly_report_html(grouped, year=year, total=total)
    with open(html_path, "w", encoding="utf-8") as fp:
        fp.write(html)
    return total


def generate_weekly_report_from_db(*, db_path: str, html_path: str, year: int) -> int:
    records = read_db_records(db_path)
    grouped, total = build_weekly_report_index(records, year=year)
    related_map = build_related_map(db_path=db_path, year=year)
    html = render_weekly_report_html(
        grouped, year=year, total=total, related_map=related_map
    )
    with open(html_path, "w", encoding="utf-8") as fp:
        fp.write(html)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a static weekly report HTML from SQLite/JSONL (category + ISO week)."
    )

    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--in", dest="in_path", help="Input JSONL path")
    source_group.add_argument("--db", dest="db_path", help="Input SQLite DB path")

    parser.add_argument(
        "--out", dest="out_path", default="report.html", help="Output HTML path"
    )
    parser.add_argument(
        "--year",
        dest="year",
        type=int,
        default=2026,
        help="Only include this calendar year (default: 2026)",
    )

    args = parser.parse_args()
    try:
        if args.db_path:
            total = generate_weekly_report_from_db(
                db_path=str(args.db_path),
                html_path=str(args.out_path),
                year=int(args.year),
            )
        else:
            total = generate_weekly_report(
                jsonl_path=str(args.in_path),
                html_path=str(args.out_path),
                year=int(args.year),
            )
    except Exception as e:  # noqa: BLE001
        _eprint(f"Failed to generate report: {e}")
        raise SystemExit(2) from e

    print(f"Wrote report with {total} summaries to {args.out_path}")


if __name__ == "__main__":
    main()
