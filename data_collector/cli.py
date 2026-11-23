"""CLI entrypoint for administration, migrations, and operational tasks."""

from __future__ import annotations

import json
import sys

import click

from data_collector.config import get_settings
from data_collector.container import build_container
from data_collector.domain.exceptions import DomainError


@click.group()
def main() -> None:
    """Data Collector 2.0 administration CLI."""


@main.group()
def admin() -> None:
    """Administrative commands."""


@admin.command("bootstrap")
@click.option("--email", required=True, help="Bootstrap admin email address")
@click.option(
    "--password",
    prompt=True,
    hide_input=True,
    confirmation_prompt=True,
    help="Admin password (>=12 chars)",
)
def bootstrap_admin(email: str, password: str) -> None:
    """Create initial superadmin account explicitly (never runs on app startup)."""
    cfg = get_settings()
    container = build_container(cfg, ensure_indexes=True)
    try:
        user = container.auth_service.bootstrap_admin(email, password)
        click.echo(json.dumps({"status": "created", "user": user}))
    except DomainError as exc:
        click.echo(json.dumps({"error": exc.code, "message": exc.message}), err=True)
        sys.exit(1)
    finally:
        container.close()


@main.command("ensure-indexes")
def ensure_indexes() -> None:
    """Create or verify MongoDB indexes."""
    cfg = get_settings()
    container = build_container(cfg, ensure_indexes=True)
    container.close()
    click.echo("Indexes verified.")


@main.command("migrate-legacy")
@click.option("--workspace-id", required=True, help="Target workspace ID for legacy records")
@click.option("--project-id", required=True, help="Target project ID")
@click.option("--source-collection", required=True, help="Legacy MongoDB collection name")
@click.option("--target-collection-id", required=True, help="Target v2 collection ID")
@click.option("--dry-run/--apply", default=True, help="Preview migration without mutating")
def migrate_legacy(
    workspace_id: str,
    project_id: str,
    source_collection: str,
    target_collection_id: str,
    dry_run: bool,
) -> None:
    """Migrate records from a legacy flat MongoDB collection into tenant-scoped `records`."""
    cfg = get_settings()
    container = build_container(cfg)
    try:
        db = container.mongo.db
        count = db[source_collection].count_documents({})
        click.echo(json.dumps({"source": source_collection, "count": count, "dry_run": dry_run}))
        if dry_run or count == 0:
            return
        migrated = 0
        for doc in db[source_collection].find({}):
            legacy_id = str(doc.pop("_id"))
            container.records.insert_one(
                workspace_id=workspace_id,
                project_id=project_id,
                collection_id=target_collection_id,
                data=doc,
                created_by="migration",
                source={
                    "type": "migration",
                    "legacy_collection": source_collection,
                    "legacy_id": legacy_id,
                },
            )
            migrated += 1
        click.echo(json.dumps({"migrated": migrated}))
    finally:
        container.close()
