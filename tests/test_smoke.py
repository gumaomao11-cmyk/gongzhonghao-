"""Smoke tests: verify imports and end-to-end mock pipeline."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from pathlib import Path

# Ensure src/ is importable when running `pytest` from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.crawler.aggregator import gather_all
from src.formatters.bjh_text import render_bjh
from src.formatters.wechat_html import render_wechat
from src.pipeline.filter import filter_and_rank
from src.pipeline.formatter import export_drafts
from src.pipeline.writer import mock_generate
from src.utils.config import load_config
from src.utils.dedup import TopicHistory
from src.utils.text import jaccard, split_paragraphs, has_ai_smell, char_count


# ============== utils.text ==============

def test_jaccard_identical():
    assert jaccard("测试文案", "测试文案") == 1.0


def test_jaccard_different():
    assert jaccard("人工智能发展", "苹果种植技术") < 0.2


def test_char_count_excludes_whitespace():
    assert char_count("hello world") == 10
    assert char_count("中 文") == 2


def test_split_paragraphs_basic():
    text = "## 小标题\n\n第一段内容。\n\n**金句**\n\n第二段。"
    paras = split_paragraphs(text)
    types = [p["type"] for p in paras]
    assert "h2" in types
    assert "quote" in types


def test_has_ai_smell_detects():
    assert has_ai_smell("作为一名AI,我来帮你")
    assert has_ai_smell("首先,我们需要...其次...最后,综上所述")
    assert not has_ai_smell("今天我们来聊点不一样的。")


# ============== filter ==============

def test_filter_blacklist():
    from src.pipeline.filter import is_blacklisted, load_blacklist
    patterns = load_blacklist("data/blacklist.txt")
    assert is_blacklisted("习近平发表讲话", patterns)
    assert not is_blacklisted("苹果发布新手机", patterns)


def test_filter_dedup_against_history(tmp_path):
    history = TopicHistory(tmp_path / "history.jsonl")
    history.add("某明星结婚", "weibo", "娱乐")
    assert history.is_duplicate("某明星结婚")
    assert not history.is_duplicate("另一件事")


def test_filter_and_rank(tmp_path):
    history = TopicHistory(tmp_path / "h.jsonl")
    topics = [
        {"title": "苹果发布新机", "score": 100000, "source": "weibo", "category": "科技"},
        {"title": "习近平访问", "score": 999999, "source": "weibo", "category": "社会"},
        {"title": "某明星结婚", "score": 50000, "source": "weibo", "category": "娱乐"},
    ]
    out = filter_and_rank(
        topics,
        blacklist_path="data/blacklist.txt",
        history=history,
        target=5,
    )
    titles = [t["title"] for t in out]
    assert "苹果发布新机" in titles
    assert "某明星结婚" in titles
    assert "习近平访问" not in titles  # blacklisted


# ============== writer mock ==============

def test_mock_generate_basic():
    art = mock_generate({"title": "测试事件", "category": "科技"}, "wechat")
    assert "title" in art and "content" in art and "tags" in art
    assert art["title"]
    assert "测试事件" in art["content"] or "测试事件" in art["title"]


# ============== formatters ==============

def test_wechat_html_render():
    paras = [
        {"type": "h2", "text": "小标题"},
        {"type": "p", "text": "正文段落"},
        {"type": "quote", "text": "金句内容"},
    ]
    html = render_wechat("测试标题", "摘要", paras)
    assert "测试标题" not in html  # title not in body
    assert "小标题" in html
    assert "金句内容" in html
    assert "section" in html  # wrapped


def test_bjh_text_render():
    paras = [
        {"type": "h2", "text": "小标题"},
        {"type": "p", "text": "正文"},
    ]
    txt = render_bjh("标题", "摘要", paras, ["科技", "AI"])
    assert "小标题" in txt
    assert "#科技" in txt
    assert "AI" in txt


# ============== formatter.export ==============

def test_export_drafts(tmp_path):
    topic = {"title": "测试事件", "source": "weibo", "category": "科技", "score": 1000}
    art = mock_generate(topic, "wechat")
    art["topic"] = topic
    art["platform"] = "wechat"
    art["digest"] = "摘要内容"
    art["tags"] = ["科技", "AI"]

    day_dir = export_drafts([art], drafts_dir=str(tmp_path / "drafts"))
    assert day_dir.exists()
    folders = [p for p in day_dir.iterdir() if p.is_dir()]
    assert len(folders) == 1
    folder = folders[0]
    assert (folder / "meta.json").exists()
    assert (folder / "title.md").exists()
    assert (folder / "wechat.html").exists()
    assert (folder / "tags.json").exists()
    assert (day_dir / "manifest.csv").exists()
    assert (day_dir / "REVIEW.md").exists()

    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    assert meta["title"]
    assert meta["platform"] == "wechat"
    assert meta["ai_generated"] is True
    assert meta["status"] == "pending"


# ============== CLI ==============

def test_cli_help_runs(capsys):
    from src.main import cli
    rc = cli(["--help"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "autopost" in out


# ============== config ==============

def test_config_load_defaults():
    cfg = load_config("nonexistent.yaml")
    assert cfg.volcengine.daily_token_budget == 100_000
    assert "wechat" in cfg.platforms
    assert "bjh" in cfg.platforms
    assert cfg.output.daily_count == 20
