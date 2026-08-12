"""LLM client (OpenAI-compatible; works with volcengine/DeepSeek/Qwen).

Heavy dependency `openai` is imported lazily so the module can be loaded
even when the SDK is not installed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..utils.config import Config
from ..utils.cost import estimate_tokens

log = logging.getLogger("autopost.llm")

if TYPE_CHECKING:
    from openai import AsyncOpenAI  # noqa: F401


@dataclass
class LLMResult:
    content: str
    input_tokens: int
    output_tokens: int
    raw: dict | None = None


class LLMError(Exception):
    """Wraps an LLM error with a human-readable hint."""

    def __init__(self, code: str, message: str, hint: str = ""):
        self.code = code
        self.message = message
        self.hint = hint
        full = f"[{code}] {message}" + (f"\n  hint: {hint}" if hint else "")
        super().__init__(full)


class LLMClient:
    """Async client for OpenAI-compatible APIs."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._client: Any = None
        if cfg.volcengine.api_key and cfg.volcengine.api_key != "YOUR_API_KEY_HERE":
            self._client = self._build_client()

    def _build_client(self):
        try:
            from openai import AsyncOpenAI  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "openai SDK not installed. Run: pip install openai>=1.30"
            ) from e
        return AsyncOpenAI(
            api_key=self.cfg.volcengine.api_key,
            base_url=self.cfg.volcengine.base_url,
            max_retries=2,
        )

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    async def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.9,
        max_tokens: int = 3000,
        json_mode: bool = False,
    ) -> LLMResult:
        if not self.is_configured:
            try:
                self._client = self._build_client()
            except RuntimeError as e:
                raise LLMError(
                    "NotConfigured",
                    str(e),
                    hint="edit config.yaml and set volcengine.api_key to a real key",
                ) from e

        kwargs: dict[str, Any] = {
            "model": self.cfg.volcengine.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            resp = await self._client.chat.completions.create(**kwargs)
        except Exception as e:
            raise self._wrap_error(e) from e

        content = resp.choices[0].message.content or ""
        usage = resp.usage
        in_tok = getattr(usage, "prompt_tokens", None) or estimate_tokens(system + user)
        out_tok = getattr(usage, "completion_tokens", None) or estimate_tokens(content)
        return LLMResult(
            content=content,
            input_tokens=in_tok,
            output_tokens=out_tok,
            raw=resp.model_dump() if hasattr(resp, "model_dump") else None,
        )

    def _wrap_error(self, e: Exception) -> LLMError:
        msg = str(e)
        code = "Unknown"
        m = re.search(r"'code':\s*'([^']+)'", msg)
        if m:
            code = m.group(1)
        m = re.search(r"Error code:\s*(\d+)", msg)
        if m:
            code = f"HTTP_{m.group(1)}"

        hint = ""
        if "InvalidEndpointOrModel.NotFound" in msg or "does not exist" in msg:
            hint = (
                f"model name {self.cfg.volcengine.model!r} is not available in your account. "
                f"Run `python -m src.main --list-models` to see what IS available."
            )
        elif "Authentication" in msg or "api_key" in msg.lower() or "401" in msg:
            hint = "api_key is wrong or expired. Re-copy from volcengine console."
        elif "Quota" in msg or "insufficient" in msg.lower() or "balance" in msg.lower():
            hint = "your Coding Plan quota is exhausted or balance is low."
        elif "429" in msg or "rate" in msg.lower():
            hint = "rate limited; lower rpm_limit in config.yaml or wait."
        elif "Network" in msg or "Connection" in msg or "timeout" in msg.lower():
            hint = "network issue; check connectivity to volcengine."

        return LLMError(code, msg, hint)

    async def chat_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.9,
        max_tokens: int = 3000,
    ) -> tuple[dict, LLMResult]:
        result = await self.chat(system, user, temperature=temperature, max_tokens=max_tokens)
        try:
            return json.loads(result.content), result
        except json.JSONDecodeError:
            m = re.search(r"\{[\s\S]*\}", result.content)
            if not m:
                raise
            return json.loads(m.group(0)), result

    async def list_models(self) -> list[dict]:
        """Call OpenAI-compatible /models endpoint and return list of model dicts."""
        if not self.is_configured:
            self._client = self._build_client()
        # OpenAI SDK exposes models() at root
        try:
            resp = await self._client.models.list()
        except AttributeError:
            # Some compatible providers don't expose .list(); fall back to raw HTTP
            try:
                import httpx
            except ImportError as e:
                raise LLMError(
                    "NoListEndpoint",
                    "this provider does not support listing models via SDK",
                    hint="check the provider's docs for the available model list, "
                         "or open the web console",
                ) from e
            url = self.cfg.volcengine.base_url.rstrip("/") + "/models"
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(url, headers={"Authorization": f"Bearer {self.cfg.volcengine.api_key}"})
                r.raise_for_status()
                return r.json().get("data", [])
        except Exception as e:
            raise self._wrap_error(e) from e
        # resp is a SyncPage-like object; iterate .data
        out: list[dict] = []
        for m in getattr(resp, "data", []):
            d = m.model_dump() if hasattr(m, "model_dump") else dict(m)
            out.append(d)
        return out


async def gather_with_rate_limit(
    coros: list,
    *,
    rpm: int = 20,
) -> list:
    if not coros:
        return []
    concurrency = max(1, min(rpm, 10))
    sem = asyncio.Semaphore(concurrency)
    interval = 60.0 / rpm
    last_called = 0.0

    async def _run(coro):
        nonlocal last_called
        async with sem:
            now = asyncio.get_event_loop().time()
            wait = max(0.0, last_called + interval - now)
            if wait > 0:
                await asyncio.sleep(wait)
            last_called = asyncio.get_event_loop().time()
            return await coro

    return await asyncio.gather(*[_run(c) for c in coros], return_exceptions=True)


async def quick_test(client: LLMClient) -> bool:
    model = client.cfg.volcengine.model
    key_preview = (client.cfg.volcengine.api_key[:6] + "***") if client.cfg.volcengine.api_key else "(empty)"
    log.info(f"quick test: model={model!r}  api_key={key_preview}  base_url={client.cfg.volcengine.base_url}")
    try:
        result = await client.chat(
            system="You are a helpful assistant.",
            user="Reply with the single word: pong",
            temperature=0.0,
            max_tokens=10,
        )
        log.info(f"OK: model replied {result.content.strip()!r} (in={result.input_tokens}, out={result.output_tokens})")
        return True
    except LLMError as e:
        log.error(f"LLM test FAILED: {e}")
        return False
    except Exception as e:
        log.error(f"LLM test FAILED (unhandled {type(e).__name__}): {e}")
        return False


async def list_available_models(client: LLMClient) -> list[str]:
    """List model IDs available to this api_key. Used by --list-models."""
    try:
        models = await client.list_models()
    except LLMError as e:
        log.error(f"failed to list models: {e}")
        if e.hint:
            log.error(f"hint: {e.hint}")
        return []
    except Exception as e:
        log.error(f"failed to list models: {e}")
        return []
    return [m.get("id", "<no id>") for m in models]
