import unittest

import web_review


class TestWebReviewRender(unittest.TestCase):
    def test_pending_items_are_highlighted(self) -> None:
        grouped = {
            "设备": {
                3: [
                    {
                        "id": 1,
                        "date": "2026-01-12",
                        "week": 3,
                        "url": "https://example.com/a",
                        "review_status": "pending",
                        "final_title": "t",
                        "final_category": "设备",
                        "final_summary": "s",
                        "user_notes": "",
                        "llm_category": "设备",
                        "llm_summary": "s",
                    }
                ]
            }
        }

        html = web_review.render_review_html(grouped, year=2026)
        self.assertIn("pending-item", html)

    def test_related_items_are_rendered(self) -> None:
        grouped = {
            "设备": {
                3: [
                    {
                        "id": 1,
                        "date": "2026-01-12",
                        "week": 3,
                        "url": "https://example.com/a",
                        "review_status": "reviewed",
                        "final_title": "t",
                        "final_category": "设备",
                        "final_summary": "主事件",
                        "user_notes": "",
                        "llm_category": "设备",
                        "llm_summary": "s",
                        "related": [
                            {
                                "id": 2,
                                "url": "https://example.com/b",
                                "date": "2026-01-02",
                                "week": 1,
                                "review_status": "reviewed",
                                "summary": "关联事件",
                            }
                        ],
                    }
                ]
            }
        }

        html = web_review.render_review_html(grouped, year=2026)
        self.assertIn("related-list", html)
        self.assertIn("关联事件", html)


if __name__ == "__main__":
    unittest.main()
