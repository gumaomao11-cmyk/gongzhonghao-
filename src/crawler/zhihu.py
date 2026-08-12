"""Zhihu hot list scraper (uses official-ish API endpoint)."""

from __future__ import annotations

import logging
from typing import AsyncIterator

from .base import random_headers

log = logging.getLogger("autopost.crawler.zhihu")

# 知乎热榜 API(需 cookie,首次访问首页拿 cookie 再请求)
HOT_LIST_URL = "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit=50"
HOME_URL = "https://www.zhihu.com"


async def fetch_zhihu_topics() -> AsyncIterator[dict]:
    """Yield topics from Zhihu hot list.

    Zhihu's API requires a valid session cookie; we obtain one by hitting the homepage
    first, then reuse the client.
    """
    try:
        import httpx  # type: ignore
    except ImportError:
        log.warning("httpx not installed; skipping zhihu")
        return

    headers = random_headers()
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            await client.get(HOME_URL, headers=headers)
            r = await client.get(HOT_LIST_URL, headers=headers)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.warning("zhihu fetch failed: %s", e)
        return

    items = data.get("data", [])
    for item in items:
        target = item.get("target", {}) or {}
        title = target.get("title_area", {}).get("text", "") or target.get("title", "")
        if not title:
            continue
        score = int(item.get("detail_text", "0").replace(",", "").split(" ")[0] or 0)
        excerpt = target.get("excerpt_area", {}).get("text", "")
        yield {
            "title": title,
            "url": f"https://www.zhihu.com/question/{target.get('id', '')}",
            "score": score,
            "source": "zhihu",
            "category": _guess_category(title, excerpt),
        }


def _guess_category(title: str, excerpt: str = "") -> str:
    text = title + " " + excerpt
    rules = {
        "娱乐": ["明星", "演员", "电影", "剧", "演唱", "粉丝"],
        "科技": ["AI", "GPT", "模型", "代码", "开源", "程序员", "算法", "芯片"],
        "社会": ["警方", "通报", "事故", "医院", "坠楼", "学生"],
        "财经": ["经济", "股市", "上市", "财报", "GDP", "投资", "基金"],
        "体育": ["比赛", "球员", "冠军", "世界杯", "奥运", "联赛"],
        "教育": ["高考", "考研", "大学", "学生", "老师", "专业"],
    }
    for cat, kws in rules.items():
        if any(k in text for k in kws):
            return cat
    return "其他"
