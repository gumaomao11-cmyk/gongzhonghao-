"""autopost — main entry. Run once, daemon, check, list-models, or show help."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

from .crawler.aggregator import gather_all
from .pipeline.filter import filter_and_rank
from .pipeline.formatter import export_drafts
from .pipeline.writer import write_articles
from .storage.db import HotTopicsDB
from .utils.config import Config, load_config
from .utils.cost import CostTracker
from .utils.dedup import TopicHistory
from .llm.client import LLMClient, LLMError, quick_test, list_available_models


def setup_logging(logs_dir: str | Path, level: str = "INFO") -> None:
    try:
        from loguru import logger as loguru_logger
    except ImportError:
        logging.basicConfig(level=level, format="%(asctime)s | %(levelname)-7s | %(message)s")
        return

    Path(logs_dir).mkdir(parents=True, exist_ok=True)
    loguru_logger.remove()
    loguru_logger.add(sys.stderr, level=level, colorize=True, format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | {message}")
    loguru_logger.add(
        Path(logs_dir) / "autopost-{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="30 days",
        encoding="utf-8",
        level="DEBUG",
    )

    class InterceptHandler(logging.Handler):
        def emit(self, record):
            try:
                level = loguru_logger.level(record.levelname).name
            except ValueError:
                level = record.levelno
            loguru_logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)


def get_logger():
    try:
        from loguru import logger as log
    except ImportError:
        log = logging.getLogger("autopost")
    return log


async def run_once(cfg: Config, *, use_mock: bool = False) -> int:
    log = get_logger()
    log.info("=== autopost pipeline start ===")

    db = HotTopicsDB(cfg.hot_topics_db)
    history = TopicHistory(cfg.generated_topics_file)
    cost = CostTracker(Path(cfg.logs_dir) / "token_usage.json")
    client = LLMClient(cfg)

    if use_mock:
        log.info("running in MOCK mode — no LLM calls, fixtures used")
    elif not client.is_configured:
        log.error("LLM not configured: set volcengine.api_key in config.yaml")
        log.error("tip: run `python -m src.main --check` to validate the config")
        return 1

    log.info("[1/5] crawling hot topics from weibo/baidu/zhihu")
    raw_topics = await gather_all()
    if not raw_topics:
        log.error("no topics collected (network blocked or all sources failed); abort")
        return 1
    db.insert_many(raw_topics)

    log.info("[2/5] filtering and ranking")
    selected = filter_and_rank(
        raw_topics,
        blacklist_path=cfg.blacklist_file,
        history=history,
        target=cfg.output.daily_count,
    )
    if not selected:
        log.error("no topics after filter (all blacklisted or duplicates); abort")
        return 1

    log.info("[3/5] generating articles (LLM)")

    async def _on_progress(done: int, total: int):
        log.info(f"  progress: {done}/{total}")

    try:
        articles = await write_articles(
            selected,
            client=client,
            cfg=cfg,
            cost=cost,
            use_mock=use_mock,
            on_progress=_on_progress,
        )
    except LLMError as e:
        log.error(f"LLM error during batch: {e}")
        return 1

    if not articles:
        log.error("no articles generated; abort")
        return 1

    log.info("[4/5] exporting drafts")
    day_dir = export_drafts(articles, drafts_dir=cfg.output.drafts_dir)

    log.info("[5/5] updating history")
    for t in selected:
        history.add(t["title"], t.get("source", ""), t.get("category", ""))

    log.info(f"=== done. drafts in: {day_dir} ===")
    log.info(f"today token usage: {cost.today()} (budget {cfg.volcengine.daily_token_budget})")
    return 0


async def run_check(cfg: Config) -> int:
    log = get_logger()
    log.info("=== autopost LLM check ===")
    key = cfg.volcengine.api_key
    key_preview = (key[:6] + "***") if key and key != "YOUR_API_KEY_HERE" else "(empty or placeholder)"
    log.info(f"config: api_key={key_preview}  model={cfg.volcengine.model!r}  base_url={cfg.volcengine.base_url}")

    if not key or key == "YOUR_API_KEY_HERE":
        log.error("api_key is empty or placeholder")
        log.error("fix: edit config.yaml, set volcengine.api_key to your real key")
        return 1

    client = LLMClient(cfg)
    if not client.is_configured:
        log.error("LLM client not configured (api_key missing?)")
        return 1

    ok = await quick_test(client)
    if not ok:
        log.error("---")
        log.error("if the error is 404 / 'model does not exist':")
        log.error("  run:  python -m src.main --list-models")
        log.error("  to see what models your api_key actually has access to")
    return 0 if ok else 1


async def run_list_models(cfg: Config) -> int:
    log = get_logger()
    log.info("=== listing available models for your api_key ===")
    log.info(f"endpoint: {cfg.volcengine.base_url}")

    if not cfg.volcengine.api_key or cfg.volcengine.api_key == "YOUR_API_KEY_HERE":
        log.error("api_key not set; cannot list models")
        return 1

    client = LLMClient(cfg)
    if not client.is_configured:
        log.error("client not configured")
        return 1

    models = await list_available_models(client)
    if not models:
        log.error("no models returned (api_key may lack 'list models' permission)")
        log.error("fallback: open https://console.volcengine.com/ark and copy a model ID manually")
        return 1

    log.success(f"found {len(models)} model(s) available to your api_key:")
    print()
    for m in models:
        marker = "  <-- currently in config.yaml" if m == cfg.volcengine.model else ""
        print(f"  - {m}{marker}")
    print()
    log.info("to use one, set volcengine.model in config.yaml and re-run --check")
    return 0


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="autopost",
        description="公众号/百家号每日爆款文自动生成系统",
    )
    parser.add_argument("--config", "-c", default="./config.yaml", help="path to config.yaml")
    parser.add_argument("--once", action="store_true", help="run pipeline once and exit")
    parser.add_argument("--daemon", action="store_true", help="long-running scheduler (06:00 daily)")
    parser.add_argument("--check", action="store_true", help="validate LLM config with one test call")
    parser.add_argument("--list-models", action="store_true", help="list models available to your api_key")
    parser.add_argument("--mock", action="store_true", help="use mock LLM (no API calls)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    setup_logging(cfg.logs_dir, level="DEBUG" if args.verbose else "INFO")

    if args.list_models:
        return asyncio.run(run_list_models(cfg))
    if args.check:
        return asyncio.run(run_check(cfg))
    if args.once:
        return asyncio.run(run_once(cfg, use_mock=args.mock))

    if args.daemon:
        try:
            from apscheduler.schedulers.blocking import BlockingScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError:
            print("ERROR: --daemon requires apscheduler. Run: pip install apscheduler>=3.10", file=sys.stderr)
            return 1
        from loguru import logger as log
        scheduler = BlockingScheduler(timezone="Asia/Shanghai")
        hour, minute = cfg.schedule.run_at.split(":")
        scheduler.add_job(
            lambda: asyncio.run(run_once(cfg, use_mock=False)),
            CronTrigger(hour=int(hour), minute=int(minute)),
            id="daily_run",
            name="daily autopost pipeline",
            max_instances=1,
            coalesce=True,
        )
        log.info(f"scheduler started; next run at {cfg.schedule.run_at} daily")
        log.info("press Ctrl+C to exit")
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            log.info("scheduler stopped")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
