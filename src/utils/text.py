"""Text utilities: jaccard, char counting, paragraph splitting."""

from __future__ import annotations

import re
from typing import Iterable

# Chinese + English stop words for similarity computation
STOP_WORDS = set(
    "的 了 和 是 在 我 你 他 她 它 们 也 就 都 还 与 或 及 而 但 如果 因为 所以 "
    "a an the and or but if is are was were be been being have has had do does did "
    "to of in on at by for from with as it this that these those".split()
)

_PUNCT_RE = re.compile(r"[\s\W_]+", re.UNICODE)
_ZH_RE = re.compile(r"[\u4e00-\u9fff]")
_BAN_RE = re.compile(
    r"作为(一名|一个)?(AI|人工智能|大语言模型)|"
    r"首先|其次|再次|最后|综上所述|总而言之|"
    r"值得注意的是|不得不说|"
    r"希望(这篇|本篇|本文).*?对您.*?有帮助"
)


def tokenize(text: str) -> set[str]:
    """Split text into tokens for similarity, lowercased, stop-words removed."""
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    tokens = [t for t in text.split() if t and t not in STOP_WORDS and len(t) > 1]
    # For Chinese: 2-gram
    chinese = "".join(_ZH_RE.findall(text))
    tokens.extend(chinese[i : i + 2] for i in range(len(chinese) - 1))
    return {t if isinstance(t, str) else "".join(t) for t in tokens}


def jaccard(a: str, b: str) -> float:
    """Jaccard similarity in [0, 1]."""
    sa, sb = tokenize(a), tokenize(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def jaccard_topk(query: str, candidates: Iterable[str], threshold: float = 0.6) -> bool:
    """Return True if query is too similar (>threshold) to any candidate."""
    q_tokens = tokenize(query)
    if not q_tokens:
        return False
    for c in candidates:
        c_tokens = tokenize(c)
        if not c_tokens:
            continue
        sim = len(q_tokens & c_tokens) / len(q_tokens | c_tokens)
        if sim > threshold:
            return True
    return False


def char_count(text: str) -> int:
    """Count characters, excluding whitespace (closer to Chinese word-count)."""
    return len(re.sub(r"\s", "", text))


def split_paragraphs(text: str) -> list[dict]:
    """Split article body into typed paragraphs for the formatter.

    Heuristic:
      - Lines starting with # or all-caps short -> h2
      - Lines wrapped in 「」 or starting with "金句:" -> quote
      - Short line (<30 chars) at end -> highlight
      - Else -> p
    """
    paragraphs: list[dict] = []
    for raw in re.split(r"\n{2,}", text.strip()):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            paragraphs.append({"type": "h2", "text": line.lstrip("#").strip()})
        elif line.startswith(("「", "『", '"', "金句", "金句：")):
            paragraphs.append({"type": "quote", "text": line.strip("「」『』""")})
        elif line.startswith("**") and line.endswith("**"):
            paragraphs.append({"type": "quote", "text": line.strip("*")})
        elif len(line) < 30 and paragraphs and paragraphs[-1]["type"] != "h2":
            paragraphs.append({"type": "highlight", "text": line})
        else:
            paragraphs.append({"type": "p", "text": line})
    return paragraphs


def has_ai_smell(text: str) -> bool:
    """Return True if text contains common AI-tell phrases."""
    return bool(_BAN_RE.search(text))
