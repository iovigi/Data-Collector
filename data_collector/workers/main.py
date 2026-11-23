"""RQ worker process entrypoint (`dc-worker`)."""

from __future__ import annotations

from rq import Worker

from data_collector.config import get_settings
from data_collector.infrastructure.logging import configure_logging
from data_collector.infrastructure.redis import RedisManager


def main() -> None:
    cfg = get_settings()
    configure_logging(cfg.log_level)
    redis_mgr = RedisManager(cfg)
    worker = Worker(["default"], connection=redis_mgr.client)
    worker.work(with_scheduler=False)
