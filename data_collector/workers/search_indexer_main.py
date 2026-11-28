"""Manual, throttled CLI/worker entrypoint for isolated external search indexing."""

from __future__ import annotations

import json
import sys

import click

from data_collector.config import get_settings
from data_collector.container import build_container


@click.group()
def main() -> None:
    """Data Collector 2.0 isolated external search indexer."""
    from data_collector.hosting.env import load_deployment_env

    load_deployment_env()


@main.command("plan")
@click.option("--collection", "collection_id", required=True, help="Logical collection ID")
@click.option("--dry-run", is_flag=True, default=True, help="Preview without writes")
def plan_cmd(collection_id: str, dry_run: bool) -> None:
    """Inspect source index readiness and cost without modifying anything."""
    _ = dry_run
    cfg = get_settings()
    c = build_container(cfg)
    try:
        click.echo(json.dumps(c.search_indexer.plan_backfill(collection_id), indent=2))
    finally:
        c.close()


@main.command("backfill")
@click.option("--collection", "collection_id", required=True, help="Logical collection ID")
@click.option("--batch-size", type=int, default=None, help="Override batch size")
@click.option("--rate", type=int, default=None, help="Max docs/sec")
@click.option("--max-runtime", type=float, default=None, help="Max runtime seconds")
@click.option("--reset", is_flag=True, default=False, help="Reset checkpoint")
@click.option("--force", is_flag=True, default=False, help="Override SEARCH_BACKFILL_ENABLED=false")
def backfill_cmd(
    collection_id: str,
    batch_size: int | None,
    rate: int | None,
    max_runtime: float | None,
    reset: bool,
    force: bool,
) -> None:
    """Run bounded, resumable backfill into external SearchBackend."""
    cfg = get_settings()
    c = build_container(cfg)
    try:
        res = c.search_indexer.backfill_collection(
            collection_id,
            batch_size=batch_size,
            max_docs_per_second=rate,
            max_runtime_seconds=max_runtime,
            reset=reset,
            force=force,
        )
        click.echo(json.dumps(res, indent=2))
    except Exception as exc:
        click.echo(json.dumps({"error": str(exc)}), err=True)
        sys.exit(1)
    finally:
        c.close()


if __name__ == "__main__":
    main()
