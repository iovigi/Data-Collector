"""Integration tests for import/export jobs, CSV formula sanitization, and idempotency."""

from __future__ import annotations

import fakeredis
import mongomock
import pytest
from data_collector.app import create_app
from data_collector.config import Settings


@pytest.fixture
def jobs_ctx(tmp_path):
    settings = Settings(
        app_env="test",
        jwt_secret_key="jobs-test-jwt-secret-key-32-bytes-long!!",
        allowed_origins=["http://localhost:3000"],
        storage_dir=str(tmp_path / "storage"),
    )
    app = create_app(
        settings,
        mongo_client=mongomock.MongoClient(),
        redis_client=fakeredis.FakeRedis(),
        ensure_indexes=True,
    )
    app.config["TESTING"] = True
    container = app.extensions["container"]
    container.auth_service.register_user("ops@example.com", "StrongPassword123!")
    with app.test_client() as client:
        tok = client.post(
            "/api/v1/auth/login",
            json={"email": "ops@example.com", "password": "StrongPassword123!"},
        ).get_json()["access_token"]
        headers = {"Authorization": f"Bearer {tok}"}
        wid = client.post(
            "/api/v1/workspaces", json={"slug": "ops-ws", "name": "Ops"}, headers=headers
        ).get_json()["id"]
        pid = client.post(
            f"/api/v1/workspaces/{wid}/projects",
            json={"slug": "proj1", "name": "P1"},
            headers=headers,
        ).get_json()["id"]
        cid = client.post(
            f"/api/v1/projects/{pid}/collections",
            json={
                "slug": "leads",
                "schema_json": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {"name": {"type": "string"}, "note": {"type": "string"}},
                },
                "searchable_fields": ["name", "note"],
            },
            headers=headers,
        ).get_json()["id"]
        yield client, headers, cid
    container.close()


def test_jsonl_import_with_row_errors_and_idempotency(jobs_ctx):
    client, headers, cid = jobs_ctx
    payload = b'{"name": "Alice", "note": "ok"}\n{bad json\n{"note": "missing name"}\n'

    r1 = client.post(
        f"/api/v1/collections/{cid}/imports?format=jsonl",
        data=payload,
        headers={**headers, "Idempotency-Key": "imp-1"},
    )
    assert r1.status_code == 202
    job = r1.get_json()
    assert job["state"] == "completed"
    assert job["progress"]["succeeded"] == 1
    assert job["progress"]["failed"] == 2
    assert len(job["errors"]) == 2

    # Idempotent replay returns same job
    r2 = client.post(
        f"/api/v1/collections/{cid}/imports?format=jsonl",
        data=payload,
        headers={**headers, "Idempotency-Key": "imp-1"},
    )
    assert r2.status_code == 202
    assert r2.get_json()["id"] == job["id"]


def test_csv_export_sanitizes_formula_injection(jobs_ctx):
    client, headers, cid = jobs_ctx
    client.post(
        f"/api/v1/collections/{cid}/records",
        json={"data": {"name": "=CMD|'/C calc'!A0", "note": "+1+1"}},
        headers=headers,
    )
    exp = client.post(
        f"/api/v1/collections/{cid}/exports",
        json={"format": "csv"},
        headers=headers,
    )
    assert exp.status_code == 202
    jid = exp.get_json()["id"]

    res = client.get(f"/api/v1/jobs/{jid}/result", headers=headers)
    assert res.status_code == 200
    assert "X-Content-SHA256" in res.headers
    csv_text = res.data.decode("utf-8")
    assert "'=CMD" in csv_text
    assert "'+1+1" in csv_text
