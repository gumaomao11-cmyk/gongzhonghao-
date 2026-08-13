"""Config loader with safe defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class VolcengineConfig:
    api_key: str = ""
    base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    model: str = "deepseek-v3-241226"
    daily_token_budget: int = 100_000
    rpm_limit: int = 20


@dataclass
class LLMConfig:
    """LLM generation parameters (separate from volcengine config to allow
    provider-agnostic tweaking)."""
    temperature: float = 1.0
    presence_penalty: float = 0.6
    frequency_penalty: float = 0.4


@dataclass
class ScheduleConfig:
    run_at: str = "06:00"


@dataclass
class OutputConfig:
    daily_count: int = 20
    drafts_dir: str = "./drafts"


@dataclass
class PlatformConfig:
    enabled: bool = True
    char_min: int = 1000
    char_max: int = 2000


@dataclass
class Config:
    volcengine: VolcengineConfig = field(default_factory=VolcengineConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    platforms: dict[str, PlatformConfig] = field(
        default_factory=lambda: {
            "wechat": PlatformConfig(char_min=1500, char_max=2500),
            "bjh": PlatformConfig(char_min=800, char_max=1500),
        }
    )
    blacklist_file: str = "./data/blacklist.txt"
    generated_topics_file: str = "./data/generated_topics.jsonl"
    hot_topics_db: str = "./data/hot_topics.db"
    logs_dir: str = "./logs"


def _strip_inline_comment(s: str) -> str:
    s = s.strip()
    if not s:
        return s
    if s[0] in ('"', "'"):
        return s
    in_str = False
    quote = ""
    for i, c in enumerate(s):
        if in_str:
            if c == quote:
                in_str = False
        else:
            if c in ('"', "'"):
                in_str = True
                quote = c
            elif c == "#":
                return s[:i].rstrip()
    return s


def _coerce(s):
    if s is None or s == "":
        return s
    if s.startswith('"') and s.endswith('"') and len(s) >= 2:
        return s[1:-1]
    if s.startswith("'") and s.endswith("'") and len(s) >= 2:
        return s[1:-1]
    if s.lower() in ("true", "yes"):
        return True
    if s.lower() in ("false", "no"):
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        import yaml
        return yaml.safe_load(text) or {}
    except ImportError:
        return _minimal_yaml(text)


def _minimal_yaml(text: str) -> dict:
    out: dict = {}
    current_key = None
    list_key = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if stripped.startswith("- "):
            value_part = _strip_inline_comment(stripped[2:].strip())
            if not list_key:
                continue
            value = value_part.strip('"').strip("'")
            parent = out
            parts = list_key.split(".")
            for k in parts[:-1]:
                parent = parent.setdefault(k, {})
            last = parts[-1]
            if not isinstance(parent.get(last), list):
                parent[last] = []
            parent[last].append(_coerce(value))
            continue
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = _strip_inline_comment(value.strip())
            if indent == 0:
                current_key = key
                list_key = None
                if value:
                    out[key] = _coerce(value)
                else:
                    out[key] = {}
            elif indent == 2 and current_key:
                container = out.setdefault(current_key, {})
                if value:
                    container[key] = _coerce(value)
                else:
                    container[key] = {}
                    list_key = f"{current_key}.{key}"
    return out


def load_config(path: str | Path | None = None) -> Config:
    if path is None:
        path = os.environ.get("AUTOPOST_CONFIG", "./config.yaml")
    path = Path(path)
    raw = _load_yaml(path)

    v = raw.get("volcengine", {}) or {}
    llm = raw.get("llm", {}) or {}
    s = raw.get("schedule", {}) or {}
    o = raw.get("output", {}) or {}
    p_raw = raw.get("platforms", {}) or {}

    platforms: dict[str, PlatformConfig] = {}
    for name in ("wechat", "bjh"):
        cfg = p_raw.get(name, {}) or {}
        platforms[name] = PlatformConfig(
            enabled=cfg.get("enabled", True),
            char_min=cfg.get("char_min", 1000),
            char_max=cfg.get("char_max", 2000),
        )

    return Config(
        volcengine=VolcengineConfig(**v),
        llm=LLMConfig(
            temperature=llm.get("temperature", 1.0),
            presence_penalty=llm.get("presence_penalty", 0.6),
            frequency_penalty=llm.get("frequency_penalty", 0.4),
        ),
        schedule=ScheduleConfig(**s),
        output=OutputConfig(**o),
        platforms=platforms,
        blacklist_file=raw.get("blacklist_file", "./data/blacklist.txt"),
        generated_topics_file=raw.get("generated_topics_file", "./data/generated_topics.jsonl"),
        hot_topics_db=raw.get("hot_topics_db", "./data/hot_topics.db"),
        logs_dir=raw.get("logs_dir", "./logs"),
    )
