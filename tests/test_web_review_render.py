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


if __name__ == "__main__":
    unittest.main()
