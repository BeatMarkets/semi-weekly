import unittest

import main


class TestLlmUtils(unittest.TestCase):
    def test_parse_llm_json_object_plain(self) -> None:
        obj = main.parse_llm_json_object('{"category":"设备","summary_zh":"一句话。"}')
        category, summary = main.normalize_and_validate_llm_result(obj)
        self.assertEqual(category, "设备")
        self.assertEqual(summary, "一句话。")

    def test_parse_llm_json_object_with_fences(self) -> None:
        text = """```json
{"category":"材料","summary_zh":"两句话。第二句。"}
```"""
        obj = main.parse_llm_json_object(text)
        category, summary = main.normalize_and_validate_llm_result(obj)
        self.assertEqual(category, "材料")
        self.assertEqual(summary, "两句话。第二句。")

    def test_truncate_summary_to_three_sentences(self) -> None:
        obj = {
            "category": "设计",
            "summary_zh": "第一句。第二句。第三句。第四句。",
        }
        category, summary = main.normalize_and_validate_llm_result(obj)
        self.assertEqual(category, "设计")
        self.assertEqual(summary, "第一句。第二句。第三句。")

    def test_build_content_excerpt_max_chars(self) -> None:
        excerpt = main.build_content_excerpt("a" * 4000, max_chars=100)
        self.assertEqual(len(excerpt), 100)


if __name__ == "__main__":
    unittest.main()
