"""Article generation pipeline with style randomization + structured parsing."""

from __future__ import annotations

import logging
import random
from typing import Awaitable, Callable

from ..llm.client import LLMClient, LLMError
from ..llm.prompts import TAG_SYSTEM, TAG_USER, get_article_system, get_article_user
from ..utils.config import Config
from ..utils.cost import CostTracker

log = logging.getLogger("autopost.writer")


MOCK_BANNER = "\u26a0\ufe0f MOCK \u6a21\u5f0f \u2014 \u8fd9\u662f\u6a21\u677f\uff0c\u4e0d\u662f AI \u751f\u6210\uff0c\u53d1\u5e03\u524d\u5fc5\u987b\u7528\u771f LLM \u91cd\u8dd1"


def mock_generate(topic: dict, platform: str) -> dict:
    title = topic["title"]
    category = topic.get("category", "\u5176\u4ed6")
    return {
        "title": f"[MOCK] {title} \u6a21\u677f\u6d4b\u8bd5\u7a3f",
        "digest": f"\u26a0\ufe0f MOCK \u6a21\u5f0f\u3002\u4eca\u5929 {title} \u4e0a\u4e86\u70ed\u641c(\u6a21\u62df)\u3002",
        "content": (
            f"{MOCK_BANNER}\n\n"
            f"# {title} \u6a21\u677f\u6d4b\u8bd5\n\n"
            f"\u26a0\ufe0f \u8fd9\u662f mock \u6570\u636e\u3002\n\n"
            f"{title} \u8fd9\u4e2a\u8bdd\u9898(\u6a21\u62df)\u70ed\u4e86\u3002\u6211\u4e2a\u4eba\u89c2\u70b9\u662f\uff1a\u522b\u5403\u74dc\u3002\n\n"
            f"\u4ec0\u4e48?\u4f60\u95ee\u6211\u4e3a\u4ec0\u4e48?\u56e0\u4e3a\u4f60\u4f1a\u80a0\u5b50\u4e0d\u8212\u670d\u3002\n\n"
            f"**\u771f\u76f8\u5f88\u7b80\u5355\u3002**\n\n"
            f"\u5f00\u73a9\u7b11\u7684\u3002\u4f60\u8981\u662f\u4e0d\u4e50\u610f\u770b\u5230\u8fd9\u91cc\u5c31\u5f53\u6211\u6ca1\u8bf4\u3002\n"
        ),
        "tags": [category, "MOCK", "\u6d4b\u8bd5", "\u6a21\u677f"],
    }


async def _gen_one_article(
    client: LLMClient,
    topic: dict,
    platform: str,
    cfg: Config,
) -> dict | None:
    """Generate one article with randomized style."""
    platform_cfg = cfg.platforms[platform]
    system = get_article_system(platform, platform_cfg.char_min, platform_cfg.char_max)
    user = get_article_user(
        topic=topic["title"],
        source=topic.get("source", ""),
        score=topic.get("score", 0),
        context=topic.get("context") or f"\u70ed\u641c\u6765\u6e90\uff1a{topic.get('source')}\uff0c\u65e0\u66f4\u591a\u4e0a\u4e0b\u6587",
    )

    # Higher temperature + presence/frequency penalty = less AI-flavored
    temperature = getattr(cfg.llm, "temperature", 1.0)
    presence_penalty = getattr(cfg.llm, "presence_penalty", 0.6)
    frequency_penalty = getattr(cfg.llm, "frequency_penalty", 0.4)

    try:
        data = await client.chat_structured(
            system, user,
            temperature=temperature,
            max_tokens=platform_cfg.char_max * 2,
            presence_penalty=presence_penalty,
            frequency_penalty=frequency_penalty,
        )
        from ..utils.cost import estimate_tokens
        return {
            "title": data.get("title") or topic["title"],
            "digest": data.get("digest", ""),
            "content": data.get("content", ""),
            "_usage": {
                "in": estimate_tokens(system + user),
                "out": estimate_tokens(data.get("content", "")),
            },
        }
    except LLMError:
        raise
    except Exception as e:
        log.error("article gen failed for %r: %s", topic["title"], e)
        return None


async def _gen_tags(client: LLMClient, article: dict) -> list[str]:
    try:
        result = await client.chat(
            system=TAG_SYSTEM,
            user=TAG_USER.format(
                title=article["title"],
                category=article.get("category", ""),
                preview=article["content"][:200],
            ),
            temperature=0.5,
            max_tokens=200,
        )
        import re
        m = re.search(r"<tags>(.*?)</tags>", result.content, re.DOTALL | re.IGNORECASE)
        if m:
            tags_raw = m.group(1)
            tags = [t.strip().lstrip("#") for t in tags_raw.replace("\uff0c", ",").split(",") if t.strip()]
            return tags
        from ..llm.client import _parse_json_lenient
        try:
            data = _parse_json_lenient(result.content)
            tags = data.get("tags", [])
            return [str(t).strip() for t in tags if t]
        except Exception:
            return []
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
                log.warning(f"[MOCK] generating fixture for {topic['title']!r}")
                art = mock_generate(topic, platform)
                art["_usage"] = {"in": 0, "out": 0}
            elif not client.is_configured:
                log.error("LLM not configured; falling back to mock for this article")
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

            if use_mock or not client.is_configured:
                tags = art.get("tags", [topic.get("category", "\u5176\u4ed6")])
            else:
                try:
                    tags = await _gen_tags(client, art)
                except LLMError as e:
                    log.warning(f"tag gen failed for {art['title']!r}: {e}")
                    tags = []
                if not tags:
                    tags = [topic.get("category", "\u5176\u4ed6")]

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
