"""Verify MOCK articles are clearly marked."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pipeline.writer import mock_generate, MOCK_BANNER
from src.pipeline.formatter import export_drafts, _is_mock_article


def test_mock_watermark_in_article():
    topic = {"title": "测试事件", "source": "weibo", "category": "科技", "score": 1000}
    art = mock_generate(topic, "wechat")
    assert "[MOCK]" in art["title"]
    assert "MOCK" in art["content"]
    print(f"  [OK] title contains [MOCK]: {art['title']!r}")


def test_is_mock_detector():
    topic = {"title": "测试事件", "source": "weibo", "category": "科技", "score": 1000}
    art = mock_generate(topic, "wechat")
    assert _is_mock_article(art) is True
    # Real article without MOCK markers
    real = {
        "title": "正常标题",
        "content": "正常内容",
        "topic": topic,
    }
    assert _is_mock_article(real) is False
    print("  [OK] _is_mock_article correctly distinguishes")


def test_export_marks_mock_in_meta():
    import tempfile
    topic = {"title": "测试事件", "source": "weibo", "category": "科技", "score": 1000}
    art = mock_generate(topic, "wechat")
    art["topic"] = topic
    art["platform"] = "wechat"
    art["tags"] = ["科技"]

    with tempfile.TemporaryDirectory() as tmp:
        day_dir = export_drafts([art], drafts_dir=tmp + "/drafts")
        folders = [p for p in day_dir.iterdir() if p.is_dir()]
        assert len(folders) == 1
        meta = __import__("json").loads((folders[0] / "meta.json").read_text(encoding="utf-8"))
        assert meta["is_mock"] is True
        assert meta["ai_generated"] is False  # mock is not real AI
        title_md = (folders[0] / "title.md").read_text(encoding="utf-8")
        assert "MOCK" in title_md
        manifest = (day_dir / "manifest.csv").read_text(encoding="utf-8-sig")
        assert "MOCK!" in manifest
        print("  [OK] meta.json has is_mock=True")
        print("  [OK] title.md contains MOCK warning")
        print("  [OK] manifest.csv marks MOCK!")


if __name__ == "__main__":
    print("=== MOCK watermark tests ===")
    test_mock_watermark_in_article()
    test_is_mock_detector()
    test_export_marks_mock_in_meta()
    print()
    print("=== all MOCK watermark tests passed ===")
