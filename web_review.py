from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from html import escape as html_escape
from typing import Any, Optional

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse

import main
import report

DEFAULT_DB_PATH = "data/semi_weekly.db"

CATEGORY_OPTIONS = report.CATEGORY_OPTIONS

app = FastAPI()


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _format_category(category: Optional[str]) -> str:
    if not category:
        return ""
    if category == "eda/ip":
        return "EDA/IP"
    return str(category)


def _year_bounds(year: int) -> tuple[str, str]:
    start = f"{year:04d}-01-01"
    end = f"{year + 1:04d}-01-01"
    return start, end


def _open_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    main.ensure_db_schema(conn)
    return conn


def _fetch_items(conn: sqlite3.Connection, *, year: int) -> list[dict[str, Any]]:
    start, end = _year_bounds(year)
    rows = conn.execute(
        """
        SELECT
          a.id,
          a.published_date,
          a.url,
          a.title,
          l.category AS llm_category,
          l.summary_zh AS llm_summary,
          r.review_status,
          r.user_title,
          r.user_category,
          r.user_summary_zh,
          r.user_notes
        FROM reviews r
        JOIN articles a ON a.id = r.article_id
        LEFT JOIN llm_results l ON l.article_id = a.id
        WHERE a.published_date >= ? AND a.published_date < ?
        ORDER BY a.published_date DESC, a.id DESC
        """,
        (start, end),
    ).fetchall()

    items: list[dict[str, Any]] = []
    for row in rows:
        published_date = str(row["published_date"])
        parsed = date.fromisoformat(published_date)
        week = int(parsed.isocalendar().week)

        final_title = row["user_title"] or row["title"]
        final_category = row["user_category"] or row["llm_category"] or "其他"
        final_summary = row["user_summary_zh"] or row["llm_summary"] or ""

        items.append(
            {
                "id": int(row["id"]),
                "date": published_date,
                "week": week,
                "url": str(row["url"]),
                "review_status": str(row["review_status"]),
                "final_title": str(final_title),
                "final_category": str(final_category),
                "final_summary": str(final_summary),
                "user_title": row["user_title"],
                "user_category": row["user_category"],
                "user_summary_zh": row["user_summary_zh"],
                "user_notes": row["user_notes"],
                "llm_category": row["llm_category"],
                "llm_summary": row["llm_summary"],
            }
        )

    return items


def _group_items(
    items: list[dict[str, Any]],
) -> dict[str, dict[int, list[dict[str, Any]]]]:
    grouped: dict[str, dict[int, list[dict[str, Any]]]] = {}

    for item in items:
        category = str(item.get("final_category") or "其他")
        if category not in CATEGORY_OPTIONS:
            category = "其他"

        week = int(item["week"])
        grouped.setdefault(category, {}).setdefault(week, []).append(item)

    for category in grouped:
        for week in grouped[category]:
            grouped[category][week].sort(key=lambda x: x["date"], reverse=True)

    return grouped


def render_review_html(
    grouped: dict[str, dict[int, list[dict[str, Any]]]], *, year: int
) -> str:
    title = f"{year} 半导体产业周报（Review）"
    subtitle = "按产业链分类 · 按全年周汇总 · 可编辑/高亮未 Review"

    css = report.render_weekly_report_html({}, year=year, total=0)
    # Extract CSS block from report HTML
    css_start = css.find("<style>")
    css_end = css.find("</style>")
    base_css = ""
    if css_start != -1 and css_end != -1:
        base_css = css[css_start + len("<style>") : css_end]

    extra_css = """
.pending-item {
  background: #fff7ed;
  border-radius: 10px;
  padding: 10px 12px;
}
.item-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.btn {
  appearance: none;
  border: 1px solid var(--border);
  background: white;
  border-radius: 10px;
  padding: 6px 10px;
  cursor: pointer;
  font-size: 12px;
}
.btn-primary {
  background: var(--blue);
  border-color: var(--blue);
  color: white;
}
.btn-danger {
  border-color: #ef4444;
  color: #ef4444;
}
.inline-form {
  margin-top: 10px;
  border-top: 1px dashed var(--border);
  padding-top: 10px;
}
.inline-form label {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin: 8px 0 4px;
}
.inline-form input[type="text"],
.inline-form textarea,
.inline-form select {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 8px 10px;
  font-size: 14px;
}
.inline-form textarea { min-height: 88px; resize: vertical; }
.muted {
  color: var(--muted);
  font-size: 12px;
}
.summary-line {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}
.summary-text { flex: 1; }
"""

    js = """
function toggleEdit(id) {
  const el = document.getElementById('edit-' + id);
  if (!el) return;
  el.style.display = (el.style.display === 'none' || el.style.display === '') ? 'block' : 'none';
}
function restoreScrollPosition() {
  const saved = sessionStorage.getItem('review-scroll');
  if (!saved) return;
  const value = Number.parseInt(saved, 10);
  if (Number.isNaN(value)) return;
  window.scrollTo(0, value);
  sessionStorage.removeItem('review-scroll');
}
function confirmDelete(id) {
  if (!confirm('确定要硬删除这条记录吗？删除后将加入忽略列表，不再入库/抓取。')) return;
  sessionStorage.setItem('review-scroll', String(window.scrollY));
  document.getElementById('del-' + id).submit();
}
window.addEventListener('load', restoreScrollPosition);
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
    parts.append(f"<style>{base_css}\n{extra_css}</style>")
    parts.append(f"<script>{js}</script>")
    parts.append("</head>")
    parts.append("<body>")
    parts.append('<div class="container">')
    parts.append('<div class="header">')
    parts.append(f"<h1>{html_escape(title)}</h1>")
    parts.append(f"<p>{html_escape(subtitle)}</p>")
    parts.append("</div>")
    parts.append('<div class="grid">')

    for category in CATEGORY_OPTIONS:
        weeks = grouped.get(category)
        if not weeks:
            continue

        parts.append('<section class="card">')
        parts.append(
            f'<div class="card-title">{html_escape(report._category_display_name(category))}</div>'
        )
        parts.append('<div class="section">')

        for week in sorted(weeks.keys(), reverse=True):
            items = list(weeks[week])
            parts.append('<div class="week">')
            parts.append(f'<div class="badge">{report._format_week_badge(week)}</div>')
            parts.append(
                f'<div class="label">{html_escape(report._format_week_label_zh(week))}</div>'
            )
            parts.append("</div>")
            parts.append('<ul class="items">')

            for item in items:
                item_id = int(item["id"])
                status = str(item["review_status"])
                is_pending = status != "reviewed"

                final_summary = str(item.get("final_summary") or "")
                if not final_summary:
                    final_summary = "（尚未生成摘要）"

                final_category = str(item.get("final_category") or "其他")

                parts.append('<li id="item-%d">' % item_id)
                wrapper_class = "pending-item" if is_pending else ""
                parts.append(f'<div class="{wrapper_class}">')

                url = html_escape(str(item.get("url", "")).strip())
                summary = html_escape(final_summary)
                parts.append('<div class="summary-line">')
                parts.append('<div class="summary-text">')
                if url:
                    parts.append(
                        f'<a href="{url}" target="_blank" rel="noopener noreferrer">{summary}</a>'
                    )
                else:
                    parts.append(summary)

                parts.append(
                    f'<div class="muted">{html_escape(item["date"])} · {_format_category(final_category)} · {html_escape(status)}</div>'
                )
                parts.append("</div>")

                parts.append("</div>")

                parts.append('<div class="item-actions">')
                parts.append(
                    f'<button class="btn" type="button" onclick="toggleEdit({item_id})">编辑</button>'
                )

                if is_pending:
                    parts.append(
                        f'<form method="post" action="/item/{item_id}/approve" style="margin:0">'
                        f'<button class="btn btn-primary" type="submit">通过</button>'
                        "</form>"
                    )

                parts.append(
                    f'<form id="del-{item_id}" method="post" action="/item/{item_id}/delete" style="margin:0">'
                    f'<button class="btn btn-danger" type="button" onclick="confirmDelete({item_id})">删除</button>'
                    "</form>"
                )

                parts.append("</div>")

                # Inline edit form
                parts.append(
                    f'<div id="edit-{item_id}" class="inline-form" style="display:none">'
                )
                parts.append(
                    f'<form method="post" action="/item/{item_id}" style="margin:0">'
                )

                parts.append("<label>标题</label>")
                parts.append(
                    f'<input type="text" name="user_title" value="{html_escape(item.get("final_title", ""))}" />'
                )

                parts.append("<label>分类</label>")
                parts.append('<select name="user_category">')
                selected = (
                    final_category if final_category in CATEGORY_OPTIONS else "其他"
                )
                for opt in CATEGORY_OPTIONS:
                    opt_label = html_escape(_format_category(opt))
                    opt_value = html_escape(opt)
                    sel = " selected" if opt == selected else ""
                    parts.append(
                        f'<option value="{opt_value}"{sel}>{opt_label}</option>'
                    )
                parts.append("</select>")

                parts.append("<label>摘要</label>")
                parts.append(
                    f'<textarea name="user_summary_zh">{html_escape(final_summary if final_summary != "（尚未生成摘要）" else "")}</textarea>'
                )

                parts.append("<label>备注</label>")
                notes = item.get("user_notes") or ""
                parts.append(
                    f'<textarea name="user_notes">{html_escape(str(notes))}</textarea>'
                )

                parts.append('<div class="item-actions">')
                parts.append(
                    '<button class="btn" type="submit" name="action" value="save">保存</button>'
                )
                parts.append(
                    '<button class="btn btn-primary" type="submit" name="action" value="save_approve">保存并通过</button>'
                )
                parts.append(
                    f'<button class="btn" type="button" onclick="toggleEdit({item_id})">取消</button>'
                )
                parts.append("</div>")

                llm_cat = item.get("llm_category")
                llm_sum = item.get("llm_summary")
                if llm_cat or llm_sum:
                    parts.append('<div class="muted">')
                    if llm_cat:
                        parts.append(
                            f"LLM 分类：{html_escape(_format_category(llm_cat))}<br/>"
                        )
                    if llm_sum:
                        parts.append(f"LLM 摘要：{html_escape(str(llm_sum))}")
                    parts.append("</div>")

                parts.append("</form>")
                parts.append("</div>")

                parts.append("</div>")
                parts.append("</li>")

            parts.append("</ul>")

        parts.append("</div>")
        parts.append("</section>")

    parts.append("</div>")
    parts.append(
        '<div class="footer">Local-only Web Review · SQLite source of truth</div>'
    )
    parts.append("</div>")
    parts.append("</body>")
    parts.append("</html>")

    return "\n".join(parts)


@app.get("/", response_class=HTMLResponse)
def index(year: int = 2026, db: str = DEFAULT_DB_PATH) -> HTMLResponse:
    conn = _open_db(db)
    try:
        items = _fetch_items(conn, year=year)
    finally:
        conn.close()

    grouped = _group_items(items)
    html = render_review_html(grouped, year=year)
    return HTMLResponse(content=html)


@app.post("/item/{item_id}")
def save_item(
    item_id: int,
    db: str = DEFAULT_DB_PATH,
    action: str = Form("save"),
    user_title: str = Form(""),
    user_category: str = Form("其他"),
    user_summary_zh: str = Form(""),
    user_notes: str = Form(""),
) -> RedirectResponse:
    now = _now_iso_utc()

    title = user_title.strip()
    summary = user_summary_zh.strip()
    notes = user_notes.strip()
    category = user_category.strip()
    if category not in CATEGORY_OPTIONS:
        category = "其他"

    conn = _open_db(db)
    try:
        with conn:
            conn.execute(
                """
                UPDATE reviews
                SET user_title = ?, user_category = ?, user_summary_zh = ?, user_notes = ?, updated_at = ?
                WHERE article_id = ?
                """,
                (title, category, summary, notes, now, item_id),
            )

            if action == "save_approve":
                conn.execute(
                    """
                    UPDATE reviews
                    SET review_status = 'reviewed', reviewed_at = COALESCE(reviewed_at, ?), updated_at = ?
                    WHERE article_id = ?
                    """,
                    (now, now, item_id),
                )
    finally:
        conn.close()

    return RedirectResponse(url=f"/#item-{item_id}", status_code=303)


@app.post("/item/{item_id}/approve")
def approve_item(item_id: int, db: str = DEFAULT_DB_PATH) -> RedirectResponse:
    now = _now_iso_utc()
    conn = _open_db(db)
    try:
        with conn:
            conn.execute(
                """
                UPDATE reviews
                SET review_status = 'reviewed', reviewed_at = COALESCE(reviewed_at, ?), updated_at = ?
                WHERE article_id = ?
                """,
                (now, now, item_id),
            )
    finally:
        conn.close()

    return RedirectResponse(url=f"/#item-{item_id}", status_code=303)


@app.post("/item/{item_id}/delete")
def delete_item(item_id: int, db: str = DEFAULT_DB_PATH) -> RedirectResponse:
    conn = _open_db(db)
    try:
        with conn:
            row = conn.execute(
                "SELECT url FROM articles WHERE id = ?",
                (item_id,),
            ).fetchone()
            if row and row["url"]:
                conn.execute(
                    "INSERT OR IGNORE INTO ignored_urls (url, created_at) VALUES (?, ?)",
                    (str(row["url"]), _now_iso_utc()),
                )
            conn.execute("DELETE FROM articles WHERE id = ?", (item_id,))
    finally:
        conn.close()

    return RedirectResponse(url="/", status_code=303)
