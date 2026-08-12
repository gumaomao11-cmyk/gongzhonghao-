"""Article generation pipeline: title + body + tags via LLM."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable

from ..llm.client import LLMClient, LLMError, gather_with_rate_limit
from ..llm.prompts import (
    ARTICLE_USER,
    TAG_USER,
    TITLE_USER,
    get_article_system,
)
from ..utils.config import Config
from ..utils.cost import CostTracker, estimate_tokens

log = logging.getLogger("autopost.writer")


# === Mock generator (for testing without LLM) ===

MOCK_BANNER = "⚠️ MOCK 模式 — 这是模板,不是 AI 生成,发布前必须用真 LLM 重跑"


def mock_generate(topic: dict, platform: str) -> dict:
    """Generate a plausible-looking article locally without LLM calls.

    Output is intentionally watermarked so it cannot be mistaken for a real article.
    """
    title = topic["title"]
    category = topic.get("category", "其他")
    return {
        "title": f"[MOCK] {title} 模板测试稿",
        "digest": f"⚠️ MOCK 模式,非真实生成。今天 {title} 上了热搜(模拟)。",
        "content": (
            f"{MOCK_BANNER}\n\n"
            f"# {title} 模板测试\n\n"
            f"⚠️ 这是 mock 数据,用于流程演示。\n\n"
            f"这两天,{title} 这个话题(模拟)彻底刷屏了。有人说这是反转,有人说是炒作。"
            f"作为一个在 {category} 领域(模拟)摸爬滚打多年的观察者,我有一些不吐不快的观点。\n\n"
            f"# 三个被忽略的细节(模拟)\n\n"
            f"第一,时间线。绝大多数讨论只截取了一个片段,如果你把过去一周的相关报道串起来看,"
            f"会发现事情远没有那么简单。\n\n"
            f"第二,角色立场。每个发声的人都有自己的利益相关,他们的表态,本身就是信息。\n\n"
            f"第三,情绪传染。社交媒体时代,流量会自我强化——这不代表真相,只代表关注度。\n\n"
            f"**真相从来不是非黑即白,而是层层叠叠的灰色。** (模拟金句)\n\n"
            f"# 我们真正该思考的\n\n"
            f"比起 {title} 本身,更值得讨论的是:为什么我们会对这样的事件如此上头?"
            f"这背后,可能藏着更深层的社会心理。\n\n"
            f"你怎么看?评论区聊聊。\n\n"
            f"---\n{MOCK_BANNER}\n"
        ),
        "tags": [category, "MOCK", "测试", "模板"],
    }


async def _gen_one_article(
    client: LLMClient,
    topic: dict,
    platform: str,
    cfg: Config,
) -> dict | None:
    """Generate one article (title + body) for a topic on a given platform."""
    platform_cfg = cfg.platforms[platform]
    system = get_article_system(platform, platform_cfg.char_min, platform_cfg.char_max)
    user = ARTICLE_USER.format(
        topic=topic["title"],
        source=topic.get("source", ""),
        score=topic.get("score", 0),
        context=topic.get("context") or f"热搜来源:{topic.get('source')},无更多上下文",
    )
    try:
        data, result = await client.chat_json(
            system, user, temperature=0.9, max_tokens=platform_cfg.char_max * 2
        )
        return {
            "title": data.get("title", topic["title"]),
            "digest": data.get("digest", ""),
            "content": data.get("content", ""),
            "_usage": {"in": result.input_tokens, "out": result.output_tokens},
        }
    except LLMError:
        raise
    except Exception as e:
        log.error("article gen failed for %r: %s", topic["title"], e)
        return None


async def _gen_tags(client: LLMClient, article: dict) -> list[str]:
    """Generate platform tags for an article."""
    try:
        data, _ = await client.chat_json(
            "你是内容运营,擅长给文章打精准分类标签。",
            TAG_USER.format(
                title=article["title"],
                category=article.get("category", ""),
                preview=article["content"][:200],
            ),
            temperature=0.5,
            max_tokens=100,
        )
        tags = data.get("tags", [])
        return [str(t).strip() for t in tags if t]
    except LLMError:
        raise
    except Exception as e:
        log.warning("tag gen failed: %s", e)
        return []


async def write_articles(
    topics: list[dict],
    *,
    client: LLMClient,
    cfg: Config,
    cost: CostTracker,
    platforms: list[str] | None = None,
    use_mock: bool = False,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> list[dict]:
    """Generate articles for all (topic × platform) pairs.

    Returns list of dicts: {topic, platform, title, digest, content, tags, usage}.

    If a single LLM call raises LLMError, the error is logged with hint and
    that article is skipped; remaining articles continue. The first LLMError
    surfaces up so the caller can decide to abort the whole batch.
    """
    if platforms is None:
        platforms = [p for p, c in cfg.platforms.items() if c.enabled]

    results: list[dict] = []
    total = len(topics) * len(platforms)
    done = 0
    budget = cfg.volcengine.daily_token_budget
    first_error: LLMError | None = None

    for topic in topics:
        for platform in platforms:
            if cost.budget_remaining(budget) <= 0:
                log.warning("daily token budget exhausted, stopping")
                return results

            if use_mock:
                log.warning(f"[MOCK] generating fixture for {topic['title']!r} (--mock is on)")
                art = mock_generate(topic, platform)
                art["_usage"] = {"in": 0, "out": 0}
            elif not client.is_configured:
                log.error("LLM not configured; falling back to mock for this article")
                log.error("fix: set volcengine.api_key in config.yaml, then re-run WITHOUT --mock")
                art = mock_generate(topic, platform)
                art["_usage"] = {"in": 0, "out": 0}
            else:
                try:
                    art = await _gen_one_article(client, topic, platform, cfg)
                except LLMError as e:
                    log.error(f"article gen failed for {topic['title']!r}: {e}")
                    if first_error is None:
                        first_error = e
                    art = None
                if art is None:
                    done += 1
                    if on_progress:
                        await on_progress(done, total)
                    continue

            # Tags
            if use_mock or not client.is_configured:
                tags = art.get("tags", [topic.get("category", "其他")])
            else:
                try:
                    tags = await _gen_tags(client, art)
                except LLMError as e:
                    log.warning(f"tag gen failed for {art['title']!r}: {e}")
                    tags = []
                if not tags:
                    tags = [topic.get("category", "其他")]

            usage = art.get("_usage", {})
            cost.add(usage.get("in", 0) + usage.get("out", 0))

            results.append(
                {
                    "topic": topic,
                    "platform": platform,
                    "title": art["title"],
                    "digest": art.get("digest", ""),
                    "content": art.get("content", ""),
                    "tags": tags,
                    "usage": usage,
                }
            )

            done += 1
            if on_progress:
                await on_progress(done, total)

    if first_error is not None and not results:
        raise first_error

    log.info(f"wrote {len(results)} articles across {len(platforms)} platforms")
    return results
