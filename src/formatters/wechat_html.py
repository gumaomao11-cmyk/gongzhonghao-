"""Render article paragraphs to WeChat-compatible HTML (inline styles only)."""

from __future__ import annotations

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"


def render_wechat(title: str, digest: str, paragraphs: list[dict]) -> str:
    """Render an article for WeChat.

    WeChat strips <style> and most CSS, so all styling is inline.
    The result is meant to be pasted into 135editor/秀米 first, then into WeChat.
    """
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(enabled_extensions=("j2",)),
    )
    tpl = env.get_template("wechat.html.j2")
    return tpl.render(paragraphs=paragraphs, title=title, digest=digest)
