"""Additional coverage for collection, record batch, pagination, auth bootstrap, and CLI."""

from __future__ import annotations

import fakeredis
import mongomock
import pytest
from click.testing import CliRunner
from data_collector.cli import main as cli_main
from data_collector.config import Settings
from data_collector.container import build_container
from data_collector.domain.exceptions import ConflictError, ValidationError
from data_collector.domain.identities import Actor, PrincipalType


@pytest.fixture
def svc_ctx():
    settings = Settings(
        app_env="test",
        jwt_secret_key="svc-test-jwt-secret-key-32-bytes-long!!",
        allowed_origins=["http://localhost:3000"],
    )
    ctr = build_container(
        settings,
        mongo_client=mongomock.MongoClient(),
        redis_client=fakeredis.FakeRedis(),
        ensure_indexes=True,
    )
    yield ctr
    ctr.close()


def test_bootstrap_admin_and_duplicate_refusal(svc_ctx):
    u = svc_ctx.auth_service.bootstrap_admin("admin@example.com", "VeryStrongAdminPass123!")
    assert u["email"] == "admin@example.com"
    with pytest.raises(ConflictError):
        svc_ctx.auth_service.bootstrap_admin("admin@example.com", "AnotherPass123!")
    with pytest.raises(ValidationError):
        svc_ctx.auth_service.bootstrap_admin("a2@example.com", "short")


def test_collection_update_batch_create_and_cursor_pagination(svc_ctx):
    u = svc_ctx.auth_service.register_user("owner@example.com", "VeryStrongPass123!")
    u2 = svc_ctx.auth_service.register_user("viewer@example.com", "VeryStrongPass123!")
    owner = Actor(principal_id=u["id"], principal_type=PrincipalType.USER)

    ws = svc_ctx.collection_service.create_workspace(owner, slug="ws-batch", name="Batch WS")
    svc_ctx.collection_service.add_member(owner, ws["id"], u2["id"], "viewer")
    proj = svc_ctx.collection_service.create_project(owner, ws["id"], slug="proj-b", name="Proj B")
    col = svc_ctx.collection_service.create_collection(
        owner,
        proj["id"],
        slug="events",
        schema_json={
            "type": "object",
            "required": ["seq"],
            "properties": {"seq": {"type": "integer"}, "tag": {"type": "string"}},
        },
        searchable_fields=["seq", "tag"],
    )

    updated = svc_ctx.collection_service.update_collection(
        owner,
        col["id"],
        searchable_fields=["seq", "tag"],
        retention_days=60,
    )
    assert updated["retention_days"] == 60

    # Batch create with 1 invalid item
    batch_res = svc_ctx.record_service.batch_create(
        owner,
        col["id"],
        [
            {"seq": 1, "tag": "a"},
            {"seq": 2, "tag": "b"},
            {"seq": 3, "tag": "c"},
            {"tag": "missing-seq"},
        ],
    )
    assert batch_res["succeeded"] == 3
    assert batch_res["failed"] == 1

    # Keyset cursor pagination
    page1 = svc_ctx.record_service.search_records(
        owner,
        col["id"],
        sort=[{"field": "seq", "direction": "asc"}],
        limit=2,
    )
    assert len(page1["items"]) == 2
    assert page1["has_more"] is True
    assert page1["next_cursor"] is not None

    page2 = svc_ctx.record_service.search_records(
        owner,
        col["id"],
        sort=[{"field": "seq", "direction": "asc"}],
        limit=2,
        cursor=page1["next_cursor"],
    )
    assert len(page2["items"]) == 1
    assert page2["has_more"] is False


def test_cli_help():
    runner = CliRunner()
    res = runner.invoke(cli_main, ["--help"])
    assert res.exit_code == 0
    assert "bootstrap" in res.output or "admin" in res.output
