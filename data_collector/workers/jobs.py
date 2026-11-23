"""RQ job entrypoints executed by dc-worker."""

from __future__ import annotations

from data_collector.container import build_container


def run_import_job(job_id: str) -> dict:
    container = build_container()
    try:
        return container.import_service.execute_import_job(job_id)
    finally:
        container.close()


def run_export_job(job_id: str) -> dict:
    container = build_container()
    try:
        return container.export_service.execute_export_job(job_id)
    finally:
        container.close()
