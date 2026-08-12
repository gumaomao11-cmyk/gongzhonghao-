"""Baidu hot search scraper (HTML parse)."""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator

from bs4 import BeautifulSoup

from .base import fetch_html

log = logging.getLogger("autopost.crawler.baidu")

URL = "https://top.baidu.com/board?tab=realtime"

# Simple Chinese->category mapping (extend as needed)
CATEGORY_HINTS = {
    "娱乐": ["明星", "主演", "演唱会", "电影", "电视剧", "综艺", "演员", "歌手"],
    "科技": ["AI", "苹果", "华为", "小米", "手机", "芯片", "模型", "开源", "GPT", "DeepSeek"],
    "社会": ["警方", "通报", "事故", "坠楼", "火灾", "地震", "医院", "地铁"],
    "财经": ["A股", "股市", "上市", "财报", "GDP", "央行", "降息"],
    "体育": ["比赛", "球员", "教练", "冠军", "联赛", "世界杯", "奥运"],
}


def _guess_category(title: str) -> str:
    for cat, keywords in CATEGORY_HINTS.items():
        if any(k in title for k in keywords):
            return cat
    return "其他"


async def fetch_baidu_topics() -> AsyncIterator[dict]:
    """Yield topics from Baidu hot search board."""
    html = await fetch_html(URL)
    if not html:
        return
    soup = BeautifulSoup(html, "lxml")
    # The board uses .category-wrap_iQLoo for each item
    items = soup.select(".category-wrap_iQLoo") or soup.select("[class*='category-wrap']")
    for item in items:
        title_el = item.select_one(".c-single-text-ellipsis") or item.select_one("a")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        if not title:
            continue
        a = item.select_one("a")
        href = a.get("href", "") if a else ""
        # Baidu uses relative URLs like /board?tab=realtime&topic=...
        url = f"https://top.baidu.com{href}" if href.startswith("/") else href
        # Hot index
        hot_el = item.select_one(".hot-index_1Bl1a") or item.select_one("[class*='hot-index']")
        hot_text = hot_el.get_text(strip=True) if hot_el else "0"
        score_match = re.search(r"\d+", hot_text.replace(",", ""))
        score = int(score_match.group(0)) if score_match else 0
        yield {
            "title": title,
            "url": url or "https://top.baidu.com/board?tab=realtime",
            "score": score,
            "source": "baidu",
            "category": _guess_category(title),
        }
