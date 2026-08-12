"""Weibo hot search scraper."""

from __future__ import annotations

import logging
from typing import AsyncIterator

from .base import fetch_json

log = logging.getLogger("autopost.crawler.weibo")

# 微博热搜公开 JSON 接口(非官方但稳定)
URL = "https://weibo.com/ajax/side/hotSearch"


async def fetch_weibo_topics() -> AsyncIterator[dict]:
    """Yield {title, url, score, source, category} from Weibo hot search."""
    data = await fetch_json(URL)
    if not data:
        return
    realtime = data.get("data", {}).get("realtime", [])
    for item in realtime:
        title = item.get("word") or item.get("note") or ""
        if not title:
            continue
        score = item.get("num", 0) or 0
        category = item.get("category", "") or item.get("label_name", "") or ""
        yield {
            "title": title,
            "url": f"https://s.weibo.com/weibo?q=%23{title}%23",
            "score": int(score),
            "source": "weibo",
            "category": category,
        }
