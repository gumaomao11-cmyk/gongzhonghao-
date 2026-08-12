"""Render article paragraphs to Baijia Hao plain-text format."""

from __future__ import annotations

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"


def render_bjh(title: str, digest: str, paragraphs: list[dict], tags: list[str]) -> str:
    """Render plain-text article for Baijia Hao (paste directly into editor)."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(enabled_extensions=("j2",)),
    )
    tpl = env.get_template("bjh.txt.j2")
    ai_notice = "⚠️ 本文由 AI 辅助创作,不代表平台立场。"
    return tpl.render(
        paragraphs=paragraphs,
        title=title,
        digest=digest,
        tags=tags,
        ai_notice=ai_notice,
    )
