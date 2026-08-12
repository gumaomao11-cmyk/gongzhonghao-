"""Topic filtering: blacklist + dedup + scoring + selection."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from ..utils.dedup import TopicHistory

log = logging.getLogger("autopost.filter")

# Default category weights (sum doesn't have to be 1, just relative)
CATEGORY_WEIGHTS: dict[str, float] = {
    "科技": 1.2,
    "社会": 1.1,
    "娱乐": 1.0,
    "体育": 0.9,
    "教育": 1.1,
    "财经": 0.8,
    "情感": 1.0,
    "其他": 0.6,
}


def load_blacklist(path: str | Path) -> list[re.Pattern]:
    """Load blacklist file, returning compiled regex patterns (one per non-comment line)."""
    path = Path(path)
    if not path.exists():
        log.warning("blacklist file not found: %s", path)
        return []
    patterns: list[re.Pattern] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            patterns.append(re.compile(re.escape(line)))
        except re.error as e:
            log.warning("bad blacklist pattern %r: %s", line, e)
    log.info("loaded %d blacklist patterns", len(patterns))
    return patterns


def is_blacklisted(title: str, patterns: list[re.Pattern]) -> bool:
    return any(p.search(title) for p in patterns)


def score_topic(
    topic: dict,
    *,
    weights: dict[str, float] | None = None,
) -> float:
    """Compute ranking score: 热度的对数 × 分类权重 × 新鲜度(当前都 1.0)。"""
    weights = weights or CATEGORY_WEIGHTS
    score = max(1, int(topic.get("score", 0)))
    # log scale so that 100k and 1M aren't that different
    import math
    heat = math.log10(score + 10)
    category = topic.get("category", "其他")
    cat_w = weights.get(category, 0.5)
    return heat * cat_w


def filter_and_rank(
    topics: list[dict],
    *,
    blacklist_path: str | Path,
    history: TopicHistory,
    target: int = 20,
    weights: dict[str, float] | None = None,
) -> list[dict]:
    """Apply blacklist, dedup, score, return top `target` topics."""
    patterns = load_blacklist(blacklist_path)
    seen: list[str] = []
    out: list[dict] = []
    for t in topics:
        title = t.get("title", "").strip()
        if not title:
            continue
        if is_blacklisted(title, patterns):
            log.debug("blacklisted: %s", title)
            continue
        if history.is_duplicate(title):
            log.debug("duplicate: %s", title)
            continue
        # local dedup within this batch
        from ..utils.text import jaccard
        if any(jaccard(title, s) > 0.6 for s in seen):
            log.debug("local-dup: %s", title)
            continue
        seen.append(title)
        t["_score"] = score_topic(t, weights=weights)
        t["selected_at"] = datetime.now().isoformat(timespec="seconds")
        out.append(t)
    out.sort(key=lambda x: x["_score"], reverse=True)
    log.info("selected %d / %d topics", min(target, len(out)), len(topics))
    return out[:target]
