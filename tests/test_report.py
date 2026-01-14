import unittest

import report


class TestReportUtils(unittest.TestCase):
    def test_to_zh_number(self) -> None:
        self.assertEqual(report._to_zh_number(1), "一")
        self.assertEqual(report._to_zh_number(10), "十")
        self.assertEqual(report._to_zh_number(11), "十一")
        self.assertEqual(report._to_zh_number(20), "二十")
        self.assertEqual(report._to_zh_number(53), "五十三")

    def test_week_labels(self) -> None:
        self.assertEqual(report._format_week_badge(1), "W01")
        self.assertEqual(report._format_week_label_zh(1), "第一周")
        self.assertEqual(report._format_week_label_zh(10), "第十周")
        self.assertEqual(report._format_week_label_zh(11), "第十一周")
        self.assertEqual(report._format_week_label_zh(20), "第二十周")
        self.assertEqual(report._format_week_label_zh(53), "第五十三周")

    def test_report_filters_year_and_summary(self) -> None:
        records = [
            {
                "date": "2025-12-31",
                "category": "设备",
                "summary_zh": "2025 should drop",
                "url": "https://example.com/2025",
            },
            {
                "date": "2026-01-01",
                "category": "设备",
                "summary_zh": "keep A",
                "url": "https://example.com/a",
            },
            {
                "date": "2026-01-02",
                "category": "设备",
                "summary_zh": "   ",
                "url": "https://example.com/empty",
            },
            {
                "date": "2026-01-03",
                "category": "未知分类",
                "summary_zh": "keep B",
                "url": "https://example.com/b",
            },
            {
                "date": "not-a-date",
                "category": "设备",
                "summary_zh": "bad date should drop",
                "url": "https://example.com/bad",
            },
        ]

        grouped, total = report.build_weekly_report_index(records, year=2026)
        self.assertEqual(total, 2)
        self.assertIn("设备", grouped)
        self.assertIn("其他", grouped)

    def test_weeks_sorted_desc_in_html(self) -> None:
        records = [
            {
                "date": "2026-01-02",
                "category": "设备",
                "summary_zh": "week1",
                "url": "https://example.com/w1",
            },
            {
                "date": "2026-01-12",
                "category": "设备",
                "summary_zh": "week3",
                "url": "https://example.com/w3",
            },
        ]
        grouped, total = report.build_weekly_report_index(records, year=2026)
        html = report.render_weekly_report_html(grouped, year=2026, total=total)
        self.assertLess(html.find("W03"), html.find("W01"))


if __name__ == "__main__":
    unittest.main()
