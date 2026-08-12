"""Format articles into the final draft structure: per-topic folder + manifest + REVIEW."""

from __future__ import annotations

import csv
import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Iterable

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..formatters.bjh_text import render_bjh
from ..formatters.wechat_html import render_wechat
from ..utils.text import char_count, has_ai_smell, split_paragraphs

log = logging.getLogger("autopost.formatter")

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"


def _safe_filename(s: str, max_len: int = 60) -> str:
    """Make a string filesystem-safe; keep Chinese characters."""
    s = re.sub(r'[\\/:*?"<>|\r\n\t]', "", s).strip()
    s = re.sub(r"\s+", " ", s)
    return s[:max_len] or "untitled"


def render_article(article: dict) -> dict:
    """Render an article dict into per-platform outputs.

    Returns {wechat_html: str, bjh_text: str, paragraphs: list[dict]}.
    """
    content = article["content"]
    paragraphs = split_paragraphs(content)
    title = article["title"]
    digest = article.get("digest", "")
    tags = article.get("tags", [])

    wechat_html = render_wechat(title, digest, paragraphs)
    bjh_text = render_bjh(title, digest, paragraphs, tags)

    return {
        "wechat_html": wechat_html,
        "bjh_text": bjh_text,
        "paragraphs": paragraphs,
    }


def _is_mock_article(article: dict) -> bool:
    """Detect whether an article came from mock_generate (so we can warn loudly)."""
    title = article.get("title", "")
    content = article.get("content", "")
    return "[MOCK]" in title or "MOCK 模式" in content


def export_drafts(
    articles: list[dict],
    *,
    drafts_dir: str | Path,
    target_date: date | None = None,
) -> Path:
    """Write all articles to a date-stamped folder. Returns the folder path."""
    target_date = target_date or date.today()
    day_dir = Path(drafts_dir) / target_date.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)

    # Loud warning if any article is from mock
    mock_count = sum(1 for a in articles if _is_mock_article(a))
    if mock_count:
        log.warning("=" * 60)
        log.warning(f"{mock_count}/{len(articles)} articles are MOCK fixtures (not real LLM output)")
        log.warning("do NOT publish these. Re-run WITHOUT --mock for real articles.")
        log.warning("=" * 60)

    manifest_rows: list[dict] = []
    title_index: list[tuple[str, str]] = []

    for i, art in enumerate(articles, 1):
        topic = art["topic"]
        platform = art["platform"]
        is_mock = _is_mock_article(art)
        topic_id = f"{i:02d}-{_safe_filename(art['title'])}"
        folder = day_dir / topic_id
        folder.mkdir(parents=True, exist_ok=True)

        rendered = render_article(art)
        char_count_v = char_count(art["content"])

        meta = {
            "id": topic_id,
            "topic_title": topic.get("title", ""),
            "topic_source": topic.get("source", ""),
            "topic_url": topic.get("url", ""),
            "category": topic.get("category", "其他"),
            "ai_generated": not is_mock,
            "is_mock": is_mock,
            "platform": platform,
            "platforms_available": [platform],
            "status": "pending",
            "title": art["title"],
            "digest": art.get("digest", ""),
            "tags": art.get("tags", []),
            "char_count": char_count_v,
            "wechat_char_count": char_count(rendered["wechat_html"]) if platform == "wechat" else 0,
            "bjh_char_count": char_count(rendered["bjh_text"]) if platform == "bjh" else 0,
            "ai_smell_warning": has_ai_smell(art["content"]),
            "created_at": topic.get("selected_at", ""),
            "cover_placeholder": f"https://picsum.photos/seed/{topic_id}/600/400",
        }
        (folder / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        title_md = (
            f"# {art['title']}\n\n"
            f"**摘要**: {art.get('digest', '')}\n\n"
            f"**分类**: {topic.get('category', '其他')}  "
            f"**字数**: {char_count_v}  "
            f"**平台**: {platform}\n\n"
            f"**标签**: {' '.join('#' + t for t in art.get('tags', []))}\n"
        )
        if is_mock:
            title_md = "⚠️⚠️⚠️ MOCK 模式 — 这是模板 ⚠️⚠️⚠️\n\n" + title_md + "\n⚠️ 不要发布这个 ⚠️\n"
        (folder / "title.md").write_text(title_md, encoding="utf-8")

        if platform == "wechat":
            (folder / "wechat.html").write_text(rendered["wechat_html"], encoding="utf-8")
        if platform == "bjh":
            (folder / "bjh.txt").write_text(rendered["bjh_text"], encoding="utf-8")

        (folder / "tags.json").write_text(
            json.dumps(art.get("tags", []), ensure_ascii=False, indent=2), encoding="utf-8"
        )

        manifest_rows.append(
            {
                "id": topic_id,
                "title": art["title"],
                "category": topic.get("category", "其他"),
                "source": topic.get("source", ""),
                "platform": platform,
                "char_count": char_count_v,
                "status": "pending",
                "is_mock": "MOCK!" if is_mock else "",
                "ai_smell": "YES" if meta["ai_smell_warning"] else "",
            }
        )
        title_index.append((topic_id, art["title"]))

    # manifest.csv
    manifest_path = day_dir / "manifest.csv"
    fieldnames = ["id", "title", "category", "source", "platform", "char_count", "status", "is_mock", "ai_smell"]
    with manifest_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(manifest_rows)

    # REVIEW.md
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=select_autoescape())
    tpl = env.get_template("review.md.j2")
    review = tpl.render(
        date=target_date.isoformat(),
        count=len(manifest_rows),
        first_id=title_index[0][0] if title_index else "",
        manifest=manifest_rows,
    )
    (day_dir / "REVIEW.md").write_text(review, encoding="utf-8")

    log.info(f"exported {len(articles)} drafts to {day_dir}")
    return day_dir
