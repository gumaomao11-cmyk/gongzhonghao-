"""Aggregate hot topics from all crawlers."""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from . import baidu, weibo, zhihu

log = logging.getLogger("autopost.crawler.agg")


async def gather_all() -> list[dict]:
    """Run all crawlers concurrently and collect topics."""
    results = await asyncio.gather(
        _collect(weibo.fetch_weibo_topics, "weibo"),
        _collect(baidu.fetch_baidu_topics, "baidu"),
        _collect(zhihu.fetch_zhihu_topics, "zhihu"),
        return_exceptions=True,
    )
    topics: list[dict] = []
    for r in results:
        if isinstance(r, Exception):
            log.error("crawler raised: %s", r)
            continue
        if isinstance(r, list):
            topics.extend(r)
    log.info("collected %d topics from all sources", len(topics))
    return topics


async def _collect(aiter_factory, source: str) -> list[dict]:
    try:
        out: list[dict] = []
        async for t in aiter_factory():
            out.append(t)
        log.info("%s: %d topics", source, len(out))
        return out
    except Exception as e:
        log.error("%s failed: %s", source, e)
        return []
