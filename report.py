from __future__ import annotations

import argparse
import json
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

    return {
        "category": category,
        "week": week,
        "date": parsed_date,
        "summary": summary,
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


def render_weekly_report_html(
    grouped: dict[str, dict[int, list[dict[str, Any]]]], *, year: int, total: int
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
.items a:hover { color: var(--blue); text-decoration: underline; }
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
                if url:
                    safe_url = html_escape(url)
                    parts.append(
                        "<li>"
                        f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer">{summary}</a>'
                        "</li>"
                    )
                else:
                    parts.append(f"<li>{summary}</li>")

            parts.append("</ul>")

        parts.append("</div>")
        parts.append("</section>")

    parts.append("</div>")
    parts.append('<div class="footer">Generated from JSONL · Static HTML</div>')
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a static weekly report HTML from JSONL (category + ISO week)."
    )
    parser.add_argument("--in", dest="in_path", required=True, help="Input JSONL path")
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
