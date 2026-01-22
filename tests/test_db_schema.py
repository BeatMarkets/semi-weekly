import sqlite3
import unittest

import main


class TestDbSchema(unittest.TestCase):
    def test_foreign_key_cascade_delete(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        main.ensure_db_schema(conn)

        now = main._now_iso_utc()
        conn.execute(
            """
            INSERT INTO articles (
              source, url, title, date_raw, published_date, author, content, content_fetched_at,
              created_at, updated_at, last_seen_at
            ) VALUES (?, ?, ?, NULL, ?, NULL, ?, ?, ?, ?, ?)
            """,
            (
                "EET-China",
                "https://example.com/a",
                "title",
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
            """
            INSERT INTO articles (
              source, url, title, date_raw, published_date, author, content, content_fetched_at,
              created_at, updated_at, last_seen_at
            ) VALUES (?, ?, ?, NULL, ?, NULL, ?, ?, ?, ?, ?)
            """,
            (
                "EET-China",
                "https://example.com/b",
                "title b",
                "2026-01-03",
                "content b",
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
            (article_id, main.REVIEW_STATUS_PENDING, now),
        )
        conn.execute(
            """
            INSERT INTO llm_results (
              article_id, model, base_url, category, summary_zh, raw_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article_id,
                "qwen-plus",
                "https://example.com",
                "设备",
                "summary",
                '{"category":"设备","summary_zh":"summary"}',
                now,
            ),
        )

        conn.execute(
            """
            INSERT INTO article_links (
              from_article_id, to_article_id, relation, note, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (article_id, article_b_id, "related", None, now),
        )

        conn.execute(
            "DELETE FROM articles WHERE id IN (?, ?)", (article_id, article_b_id)
        )

        self.assertEqual(conn.execute("SELECT COUNT(1) FROM articles").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(1) FROM reviews").fetchone()[0], 0)
        self.assertEqual(
            conn.execute("SELECT COUNT(1) FROM llm_results").fetchone()[0], 0
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(1) FROM article_links").fetchone()[0], 0
        )

        conn.close()


if __name__ == "__main__":
    unittest.main()
