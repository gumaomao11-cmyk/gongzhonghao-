"""LLM client (OpenAI-compatible; works with volcengine/DeepSeek/Qwen/GLM/etc)."""

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
    def __init__(self, code: str, message: str, hint: str = ""):
        self.code = code
        self.message = message
        self.hint = hint
        full = f"[{code}] {message}" + (f"\n  hint: {hint}" if hint else "")
        super().__init__(full)


class LLMClient:
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
        presence_penalty: float = 0.0,
        frequency_penalty: float = 0.0,
    ) -> LLMResult:
        if not self.is_configured:
            try:
                self._client = self._build_client()
            except RuntimeError as e:
                raise LLMError(
                    "NotConfigured", str(e),
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
        # Only add penalties if non-zero (some providers reject 0)
        if presence_penalty:
            kwargs["presence_penalty"] = presence_penalty
        if frequency_penalty:
            kwargs["frequency_penalty"] = frequency_penalty
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
                f"model name {self.cfg.volcengine.model!r} is not available. "
                f"Run `python -m src.main --list-models` to see what IS available."
            )
        elif "Authentication" in msg or "api_key" in msg.lower() or "401" in msg:
            hint = "api_key is wrong or expired. Re-copy from provider console."
        elif "Quota" in msg or "insufficient" in msg.lower() or "balance" in msg.lower():
            hint = "quota exhausted or balance is low."
        elif "429" in msg or "rate" in msg.lower():
            hint = "rate limited; lower rpm_limit in config.yaml or wait."
        elif "Network" in msg or "Connection" in msg or "timeout" in msg.lower():
            hint = "network issue; check connectivity to provider."

        return LLMError(code, msg, hint)

    async def chat_structured(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.9,
        max_tokens: int = 3000,
        presence_penalty: float = 0.0,
        frequency_penalty: float = 0.0,
    ) -> dict:
        result = await self.chat(
            system, user,
            temperature=temperature,
            max_tokens=max_tokens,
            presence_penalty=presence_penalty,
            frequency_penalty=frequency_penalty,
        )
        return _parse_structured_response(result.content)

    async def chat_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.9,
        max_tokens: int = 3000,
    ) -> tuple[dict, LLMResult]:
        result = await self.chat(system, user, temperature=temperature, max_tokens=max_tokens)
        return _parse_json_lenient(result.content), result

    async def list_models(self) -> list[dict]:
        if not self.is_configured:
            self._client = self._build_client()
        try:
            resp = await self._client.models.list()
        except AttributeError:
            try:
                import httpx
            except ImportError as e:
                raise LLMError(
                    "NoListEndpoint",
                    "this provider does not support listing models via SDK",
                    hint="check the provider's docs or open the web console",
                ) from e
            url = self.cfg.volcengine.base_url.rstrip("/") + "/models"
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(url, headers={"Authorization": f"Bearer {self.cfg.volcengine.api_key}"})
                r.raise_for_status()
                return r.json().get("data", [])
        except Exception as e:
            raise self._wrap_error(e) from e
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


def _parse_structured_response(text: str) -> dict:
    """Parse <title>...</title> <digest>...</digest> <content>...</content>.

    Falls back to JSON, then to raw text. Never crashes.
    """
    out = _parse_tagged(text)
    if out and out.get("content"):
        return out
    try:
        parsed = _parse_json_lenient(text)
        if isinstance(parsed, dict) and (parsed.get("content") or parsed.get("title")):
            return {
                "title": parsed.get("title", "").strip(),
                "digest": parsed.get("digest", "").strip(),
                "content": parsed.get("content", "").strip() or parsed.get("text", "").strip(),
            }
    except (json.JSONDecodeError, ValueError):
        pass
    log.warning("LLM response did not contain <content> tag or valid JSON; using raw text as content")
    return {"title": "", "digest": "", "content": text.strip()}


def _parse_tagged(text: str) -> dict:
    s = re.sub(r"^```(?:[a-z]*)?\s*\n?", "", text.strip(), flags=re.MULTILINE)
    s = re.sub(r"\n?```\s*$", "", s, flags=re.MULTILINE)

    def _extract(tag: str) -> str:
        m = re.search(
            rf"<{tag}>\s*(.*?)\s*</{tag}>",
            s,
            re.DOTALL | re.IGNORECASE,
        )
        return m.group(1).strip() if m else ""

    title = _extract("title")
    digest = _extract("digest")
    content = _extract("content")
    if not content:
        return {}
    return {"title": title, "digest": digest, "content": content}


def _parse_json_lenient(text: str) -> dict:
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*\n?", "", s, flags=re.MULTILINE)
    s = re.sub(r"\n?```\s*$", "", s, flags=re.MULTILINE)

    start = s.find("{")
    if start == -1:
        raise json.JSONDecodeError("no JSON object found", s, 0)

    depth = 0
    in_str = False
    escape = False
    end = -1
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i
                break

    if end == -1:
        raise json.JSONDecodeError("unbalanced braces", s, start)

    candidate = s[start : end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return json.loads(candidate, strict=False)
