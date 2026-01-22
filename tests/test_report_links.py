import sqlite3
import tempfile
import unittest

import main
import report


class TestReportLinks(unittest.TestCase):
    def test_report_renders_related_items(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = f"{td}/semi_weekly.db"
            html_path = f"{td}/report.html"

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            main.ensure_db_schema(conn)

            now = main._now_iso_utc()
            conn.execute(
                """
                INSERT INTO articles (
                  source, url, title, date_raw, published_date, author, content, content_fetched_at,
                  created_at, updated_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    "EET-China",
                    "https://example.com/a",
                    "A title",
                    "2026-01-12",
                    "2026-01-12",
                    "content",
                    now,
                    now,
                    now,
                    now,
                ),
            )
            article_a_id = conn.execute(
                "SELECT id FROM articles WHERE url = ?",
                ("https://example.com/a",),
            ).fetchone()["id"]

            conn.execute(
                """
                INSERT INTO articles (
                  source, url, title, date_raw, published_date, author, content, content_fetched_at,
                  created_at, updated_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    "EET-China",
                    "https://example.com/b",
                    "B title",
                    "2026-01-02",
                    "2026-01-02",
                    "content",
                    now,
                    now,
                    now,
                    now,
                ),
            )
            article_b_id = conn.execute(
                "SELECT id FROM articles WHERE url = ?",
                ("https://example.com/b",),
            ).fetchone()["id"]

            conn.execute(
                """
                INSERT INTO reviews (
                  article_id, review_status, user_summary_zh, updated_at, reviewed_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (article_a_id, main.REVIEW_STATUS_REVIEWED, "主事件", now, now),
            )
            conn.execute(
                """
                INSERT INTO reviews (
                  article_id, review_status, user_summary_zh, updated_at, reviewed_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (article_b_id, main.REVIEW_STATUS_REVIEWED, "关联事件", now, now),
            )

            conn.execute(
                """
                INSERT INTO article_links (
                  from_article_id, to_article_id, relation, note, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (article_a_id, article_b_id, "related", None, now),
            )
            conn.commit()
            conn.close()

            report.generate_weekly_report_from_db(
                db_path=db_path, html_path=html_path, year=2026
            )
            with open(html_path, "r", encoding="utf-8") as fp:
                html = fp.read()

            self.assertIn("related-list", html)
            self.assertEqual(html.count("关联事件"), 1)


if __name__ == "__main__":
    unittest.main()
