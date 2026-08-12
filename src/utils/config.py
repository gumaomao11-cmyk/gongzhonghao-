"""Config loader with safe defaults.

Heavy dep `PyYAML` is imported lazily so this module loads even when missing
(a minimal stdlib fallback parses a tiny subset of YAML used in config.example.yaml).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class VolcengineConfig:
    api_key: str = ""
    base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    model: str = "deepseek-v3"
    daily_token_budget: int = 100_000
    rpm_limit: int = 20


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
    """Remove trailing `# comment` from a value, but only outside quoted strings."""
    s = s.strip()
    if not s:
        return s
    # If the value starts with a quote, the first # is part of the value (no stripping)
    if s[0] in ('"', "'"):
        return s
    # Find unquoted # (rough heuristic: first # not preceded by whitespace inside a string)
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


def _coerce(s: str):
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
    """Load YAML; fall back to a minimal parser if PyYAML is missing."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except ImportError:
        return _minimal_yaml(text)


def _minimal_yaml(text: str) -> dict:
    """Very small YAML subset parser for fallback when PyYAML is missing.

    Supports: top-level keys, 2-space indented mappings, lists with `- value`.
    Good enough for config.example.yaml but NOT for arbitrary YAML.
    """
    out: dict = {}
    current_key: str | None = None
    list_key: str | None = None
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
    """Load config from YAML; missing keys get defaults."""
    if path is None:
        path = os.environ.get("AUTOPOST_CONFIG", "./config.yaml")
    path = Path(path)
    raw = _load_yaml(path)

    v = raw.get("volcengine", {}) or {}
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
        schedule=ScheduleConfig(**s),
        output=OutputConfig(**o),
        platforms=platforms,
        blacklist_file=raw.get("blacklist_file", "./data/blacklist.txt"),
        generated_topics_file=raw.get("generated_topics_file", "./data/generated_topics.jsonl"),
        hot_topics_db=raw.get("hot_topics_db", "./data/hot_topics.db"),
        logs_dir=raw.get("logs_dir", "./logs"),
    )
