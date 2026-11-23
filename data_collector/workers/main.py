"""RQ worker process entrypoint (`dc-worker`).

On POSIX the standard forking ``rq.Worker`` is used. Windows has no ``os.fork`` and no
``SIGALRM``, so there the worker runs jobs in-process with ``SimpleWorker`` and enforces
job timeouts with ``TimerDeathPenalty``. The worker is a plain Redis consumer: it opens no
HTTP listener.

A small maintenance thread runs alongside the worker:
* hourly Redis/Garnet ``BGSAVE`` so an append-only log cannot grow without bound;
* deletion of application log files older than ``LOG_RETENTION_DAYS``.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from rq import SimpleWorker, Worker
from rq.timeouts import TimerDeathPenalty

from data_collector.config import Settings, get_settings
from data_collector.infrastructure.job_queue import QUEUE_NAME
from data_collector.infrastructure.logging import configure_logging
from data_collector.infrastructure.redis import RedisManager

logger = logging.getLogger(__name__)

LOG_RETENTION_DAYS = 14
MAINTENANCE_INTERVAL_SECONDS = 3600


class WindowsSimpleWorker(SimpleWorker):
    """In-process worker with thread-timer based job timeouts (no fork, no SIGALRM)."""

    death_penalty_class = TimerDeathPenalty


def build_worker(redis_client: Any, *, windows: bool | None = None) -> Worker:
    is_windows = (os.name == "nt") if windows is None else windows
    cls: type[Worker] = WindowsSimpleWorker if is_windows else Worker
    return cls([QUEUE_NAME], connection=redis_client)


def run_maintenance_once(cfg: Settings, redis_client: Any) -> None:
    with contextlib.suppress(Exception):
        redis_client.bgsave()
    if cfg.log_dir:
        cutoff = time.time() - LOG_RETENTION_DAYS * 86400
        for path in Path(cfg.log_dir).glob("*.log*"):
            with contextlib.suppress(OSError):
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()


def _maintenance_loop(cfg: Settings, redis_client: Any, stop: threading.Event) -> None:
    while not stop.wait(MAINTENANCE_INTERVAL_SECONDS):
        try:
            run_maintenance_once(cfg, redis_client)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Maintenance pass failed")


def main() -> None:
    from data_collector.hosting.env import load_deployment_env

    load_deployment_env()
    cfg = get_settings()
    configure_logging(cfg.log_level, stream=sys.stdout)
    redis_mgr = RedisManager(cfg)
    if not redis_mgr.ping():
        logger.error("Redis is unreachable; worker cannot start")
        sys.exit(2)

    stop = threading.Event()
    threading.Thread(
        target=_maintenance_loop, args=(cfg, redis_mgr.client, stop), daemon=True
    ).start()

    worker = build_worker(redis_mgr.client)
    logger.info(
        "Worker starting",
        extra={"extra_fields": {"worker_class": type(worker).__name__, "queue": QUEUE_NAME}},
    )
    try:
        worker.work(with_scheduler=False)
    finally:
        stop.set()
