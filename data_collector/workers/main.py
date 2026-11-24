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


def server_supports_streams(redis_client: Any) -> bool:
    """True unless the server rejects stream commands (e.g. Microsoft Garnet)."""
    from redis.exceptions import ResponseError

    try:
        redis_client.execute_command("XLEN", "dc:probe:streams")
    except ResponseError as exc:
        if "unknown command" in str(exc).lower():
            return False
        raise
    return True


def disable_rq_stream_results() -> None:
    """Make RQ's per-job result record (a Redis Stream, ``XADD``) a no-op.

    RQ 2.x writes a stream entry for every finished/failed job and has no switch to turn
    that off; on a server without Streams the ``XADD`` fails *after* the job ran and kills
    the worker. Data Collector never reads RQ results - job state, progress, errors and
    artifacts are tracked in MongoDB by the services - so skipping them loses nothing.
    Queueing, registries and worker heartbeats use lists/sets/sorted sets only.
    """
    from rq.results import Result

    def _skip_save(self: Any, ttl: Any, pipeline: Any = None) -> None:  # noqa: ARG001
        return None

    Result.save = _skip_save  # type: ignore[method-assign]


def build_worker(redis_client: Any, *, windows: bool | None = None) -> Worker:
    is_windows = (os.name == "nt") if windows is None else windows
    cls: type[Worker] = WindowsSimpleWorker if is_windows else Worker
    return cls([QUEUE_NAME], connection=redis_client)


POLL_INTERVAL_SECONDS = 1.0
REGISTRY_MAINTENANCE_SECONDS = 600


def run_polling(redis_client: Any, stop: threading.Event, *, windows: bool | None = None) -> None:
    """Consume the queue with non-blocking dequeues only (RQ burst mode in a loop).

    A worker blocked in ``BLPOP`` keeps a server-side waiter. Microsoft Garnet (2.2.x) keeps
    that waiter after the client process dies and hands it the next pushed item, so the
    first job after any worker restart/crash is silently lost. Burst mode dequeues with
    plain ``LPOP``: no server-side waiter exists, nothing can be lost, and a stop request
    is honoured within ~1 s instead of after the blocking timeout.
    """
    from rq.utils import now

    last_maintenance = 0.0
    while not stop.is_set():
        worker = build_worker(redis_client, windows=windows)
        if time.time() - last_maintenance < REGISTRY_MAINTENANCE_SECONDS:
            worker.last_cleaned_at = now()  # registry cleanup only every 10 minutes
        else:
            last_maintenance = time.time()
        worker.work(burst=True, with_scheduler=False, logging_level="WARNING")
        if worker._stop_requested:  # SIGINT/SIGTERM during a job: warm shutdown done
            break
        stop.wait(POLL_INTERVAL_SECONDS)


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

    if not server_supports_streams(redis_mgr.client):
        disable_rq_stream_results()
        logger.warning("Redis server has no Streams support; RQ result records disabled")

    stop = threading.Event()
    threading.Thread(
        target=_maintenance_loop, args=(cfg, redis_mgr.client, stop), daemon=True
    ).start()

    logger.info(
        "Worker starting (non-blocking polling)",
        extra={
            "extra_fields": {
                "worker_class": type(build_worker(redis_mgr.client)).__name__,
                "queue": QUEUE_NAME,
                "poll_seconds": POLL_INTERVAL_SECONDS,
            }
        },
    )
    try:
        run_polling(redis_mgr.client, stop)
    except KeyboardInterrupt:
        logger.info("Worker stop requested")
    finally:
        stop.set()
