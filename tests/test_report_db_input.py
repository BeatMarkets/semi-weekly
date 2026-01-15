import sqlite3
import tempfile
import unittest

import main
import report


class TestReportDbInput(unittest.TestCase):
    def test_read_db_records_only_reviewed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = f"{td}/semi_weekly.db"
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
                    "title",
                    "2026-01-02",
                    "2026-01-02",
                    "content",
                    now,
                    now,
                    now,
                    now,
                ),
            )
            article_id = conn.execute(
                "SELECT id FROM articles WHERE url = ?", ("https://example.com/a",)
            ).fetchone()["id"]

            conn.execute(
                "INSERT INTO llm_results (article_id, model, base_url, category, summary_zh, raw_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    article_id,
                    "qwen-plus",
                    "https://example.com",
                    "设备",
                    "llm summary",
                    '{"category":"设备","summary_zh":"llm summary"}',
                    now,
                ),
            )
            conn.execute(
                "INSERT INTO reviews (article_id, review_status, updated_at, reviewed_at) VALUES (?, ?, ?, ?)",
                (article_id, main.REVIEW_STATUS_REVIEWED, now, now),
            )

            # pending should not appear
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
                    "title b",
                    "2026-01-03",
                    "2026-01-03",
                    "content",
                    now,
                    now,
                    now,
                    now,
                ),
            )
            article_b_id = conn.execute(
                "SELECT id FROM articles WHERE url = ?", ("https://example.com/b",)
            ).fetchone()["id"]
            conn.execute(
                "INSERT INTO reviews (article_id, review_status, updated_at) VALUES (?, ?, ?)",
                (article_b_id, main.REVIEW_STATUS_PENDING, now),
            )

            conn.commit()
            conn.close()

            records = report.read_db_records(db_path)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["url"], "https://example.com/a")
            self.assertEqual(records[0]["category"], "设备")
            self.assertEqual(records[0]["summary_zh"], "llm summary")


if __name__ == "__main__":
    unittest.main()
