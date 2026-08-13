"""Smoke test: verify _parse_json_lenient handles all the LLM quirks we have seen."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.llm.client import _parse_json_lenient


def test_normal_json():
    assert _parse_json_lenient('{"a": 1, "b": "x"}') == {"a": 1, "b": "x"}
    print("  [OK] normal JSON")


def test_markdown_fences():
    out = _parse_json_lenient('```json\n{"a": 1}\n```')
    assert out == {"a": 1}
    print("  [OK] markdown fences stripped")


def test_unescaped_newlines():
    """The real bug: LLM returns JSON where content string has real \\n in it."""
    text = '{"title": "test", "content": "first line\nsecond line\n\n**bold**"}'
    out = _parse_json_lenient(text)
    assert out["title"] == "test"
    assert "first line" in out["content"]
    assert "**bold**" in out["content"]
    print("  [OK] unescaped newlines in content (strict=False fallback)")


def test_braces_in_content():
    text = '{"title": "代码示例", "content": "看这段: {x: 1, y: 2} 懂了没?"}'
    out = _parse_json_lenient(text)
    assert "x: 1" in out["content"]
    print("  [OK] braces inside content string")


def test_prose_around_json():
    text = '好的,以下是 JSON 结果:\n{"title": "t", "content": "c"}\n如果需要修改请告诉我。'
    out = _parse_json_lenient(text)
    assert out == {"title": "t", "content": "c"}
    print("  [OK] leading/trailing prose stripped")


def test_chinese_unicode():
    text = '{"title": "微信要用AI杀死社交吗", "content": "今天我们来聊点不一样的。\\n\\n**金句**"}'
    out = _parse_json_lenient(text)
    assert out["title"] == "微信要用AI杀死社交吗"
    print("  [OK] Chinese unicode preserved")


if __name__ == "__main__":
    print("=== _parse_json_lenient smoke tests ===")
    test_normal_json()
    test_markdown_fences()
    test_unescaped_newlines()
    test_braces_in_content()
    test_prose_around_json()
    test_chinese_unicode()
    print()
    print("=== all 6 tests passed ===")
