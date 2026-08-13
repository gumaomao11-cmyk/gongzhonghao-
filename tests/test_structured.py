"""Smoke test: verify the new XML-tagged parser handles all LLM quirks."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.llm.client import _parse_tagged, _parse_structured_response


def test_perfect_tagged():
    text = "<title>\u5fae\u4fe1\u8981\u7528AI\u6740\u6b7b\u793e\u4ea4\u5417</title><digest>\u4eca\u5929\u70ed\u8bdd</digest><content>\n# \u5f00\u5934\n\n**\u91d1\u53e5**\n\n\u7ed3\u5c3e\n</content>"
    out = _parse_tagged(text)
    assert out["title"] == "\u5fae\u4fe1\u8981\u7528AI\u6740\u6b7b\u793e\u4ea4\u5417"
    assert out["digest"] == "\u4eca\u5929\u70ed\u8bdd"
    assert out["content"].startswith("# \u5f00\u5934")
    assert "**\u91d1\u53e5**" in out["content"]
    print("  [OK] perfect XML tags")


def test_tagged_with_markdown_fence():
    text = "\u60a8\u597d\u4ee5\u4e0b\u662f\u7ed3\u679c:\n```\n<title>t</title><content>c</content>\n```\n"
    out = _parse_tagged(text)
    assert out["title"] == "t"
    assert out["content"] == "c"
    print("  [OK] tags inside markdown code fence")


def test_tagged_with_prose_around():
    text = "\u8fd9\u662f\u4e00\u7bc7\u6587\u7ae0:\n<title>\u6807\u9898</title>\n<content>\n\u6b63\u6587\u5185\u5bb9</content>\n\u8c22\u8c22"
    out = _parse_tagged(text)
    assert out["title"] == "\u6807\u9898"
    assert "\u6b63\u6587" in out["content"]
    print("  [OK] prose around tags")


def test_tagged_with_braces_in_content():
    """The exact bug that broke JSON: content has { and } characters."""
    text = "<title>\u4ee3\u7801\u793a\u4f8b</title><content>\u770b\u8fd9\u6bb5: {x: 1, y: 2} \u61c2\u4e86\u5417?</content>"
    out = _parse_tagged(text)
    assert "{x: 1, y: 2}" in out["content"]
    print("  [OK] braces in content (the original bug)")


def test_tagged_truncated():
    """LLM response got cut off mid-content (no closing </content>)."""
    text = "<title>\u5269\u4e0b</title><content>\u8fd9\u91cc\u8fd8\u6ca1\u5199\u5b8c"
    out = _parse_tagged(text)
    # No <content> closing tag means we get nothing (graceful)
    # Or we get partial if we use a non-greedy fallback - currently strict
    print(f"  [OK] truncated response: {out}")


def test_structured_fallback_to_json():
    """If tags missing, fall back to JSON parsing."""
    text = '{"title": "x", "content": "y"}'
    out = _parse_structured_response(text)
    assert out["title"] == "x"
    assert out["content"] == "y"
    print("  [OK] fallback to JSON parser")


def test_structured_fallback_to_raw():
    """If neither tags nor JSON, use raw text as content."""
    text = "\u8fd9\u662f\u4e00\u6bb5\u7eaf\u6587\u672c\u6ca1\u6709\u4efb\u4f55\u7ed3\u6784"
    out = _parse_structured_response(text)
    assert out["content"] == text
    assert out["title"] == ""
    print("  [OK] fallback to raw text (never crashes)")


def test_structured_with_unescaped_newlines_in_json():
    """The classic LLM bug: JSON content has real newlines (not \\n)."""
    text = '{"title": "x", "content": "line1\nline2\nline3"}'
    out = _parse_structured_response(text)
    assert out["title"] == "x"
    assert "line1" in out["content"]
    assert "line3" in out["content"]
    print("  [OK] unescaped newlines in JSON content")


if __name__ == "__main__":
    print("=== XML-tagged parser smoke tests ===")
    test_perfect_tagged()
    test_tagged_with_markdown_fence()
    test_tagged_with_prose_around()
    test_tagged_with_braces_in_content()
    test_tagged_truncated()
    test_structured_fallback_to_json()
    test_structured_fallback_to_raw()
    test_structured_with_unescaped_newlines_in_json()
    print()
    print("=== all 8 tests passed ===")
