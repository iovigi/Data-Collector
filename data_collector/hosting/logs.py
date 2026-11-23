"""File logging for IIS FastCGI processes.

IIS may run several FastCGI processes at once, and Windows cannot rename a file another
process has open, so size-based rotation of one shared file is unsafe. Each process writes
to ``<log_dir>/app-YYYYMMDD-<pid>.log``; the worker deletes files past retention.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from data_collector.infrastructure.logging import JsonFormatter


class DailyPerProcessFileHandler(logging.Handler):
    def __init__(self, log_dir: str, prefix: str = "app") -> None:
        super().__init__()
        self._dir = Path(log_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._prefix = prefix
        self._day = ""
        self._stream: object | None = None

    def _ensure_stream(self) -> None:
        day = datetime.now(UTC).strftime("%Y%m%d")
        if day != self._day or self._stream is None:
            if self._stream is not None:
                self._stream.close()  # type: ignore[attr-defined]
            path = self._dir / f"{self._prefix}-{day}-{os.getpid()}.log"
            self._stream = path.open("a", encoding="utf-8")
            self._day = day

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.acquire()
            try:
                self._ensure_stream()
                self._stream.write(msg + "\n")  # type: ignore[attr-defined]
                self._stream.flush()  # type: ignore[attr-defined]
            finally:
                self.release()
        except Exception:
            self.handleError(record)


def configure_file_logging(level: str, log_dir: str, prefix: str = "app") -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    handler = DailyPerProcessFileHandler(log_dir, prefix)
    handler.setFormatter(JsonFormatter())
    root.handlers.clear()
    root.addHandler(handler)
