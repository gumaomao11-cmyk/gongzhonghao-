"""Common crawler plumbing: HTTP fetch with retries, timeouts, fake UA.

Heavy dependency `httpx` is imported lazily so this module loads even when
the SDK is not installed (e.g. when running unit tests with fixtures only).
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

log = logging.getLogger("autopost.crawler")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]


def random_headers() -> dict[str, str]:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


def _httpx():
    """Lazy import of httpx; raises a clear error if missing."""
    try:
        import httpx  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "httpx not installed. Run: pip install httpx>=0.27"
        ) from e
    return httpx


async def fetch_json(
    url: str,
    *,
    params: dict | None = None,
    timeout: float = 10.0,
    retries: int = 3,
) -> dict[str, Any] | None:
    """Fetch JSON with retries. Returns None on final failure."""
    httpx = _httpx()
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                r = await client.get(url, params=params, headers=random_headers())
                r.raise_for_status()
                return r.json()
        except (httpx.HTTPError, asyncio.TimeoutError) as e:
            last_err = e
            log.warning("fetch %s attempt %d failed: %s", url, attempt, e)
            await asyncio.sleep(0.5 * attempt)
    log.error("fetch %s failed after %d retries: %s", url, retries, last_err)
    return None


async def fetch_html(
    url: str,
    *,
    timeout: float = 10.0,
    retries: int = 3,
) -> str | None:
    """Fetch HTML text with retries. Returns None on final failure."""
    httpx = _httpx()
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                r = await client.get(url, headers=random_headers())
                r.raise_for_status()
                return r.text
        except (httpx.HTTPError, asyncio.TimeoutError) as e:
            last_err = e
            log.warning("fetch %s attempt %d failed: %s", url, attempt, e)
            await asyncio.sleep(0.5 * attempt)
    log.error("fetch %s failed after %d retries: %s", url, retries, last_err)
    return None
