"""Flask application factory for Data Collector 2.0."""

from __future__ import annotations

import hmac
from typing import Any

from flask import Flask, Response, jsonify, request
from flask_cors import CORS
from pymongo import MongoClient

from data_collector.api.errors import register_error_handlers
from data_collector.api.middleware import register_middleware
from data_collector.api.openapi import build_openapi_spec
from data_collector.api.v1 import create_v1_blueprint
from data_collector.config import Settings, get_settings
from data_collector.container import Container, build_container
from data_collector.domain.exceptions import AuthenticationError
from data_collector.infrastructure.logging import configure_logging
from data_collector.infrastructure.metrics import render_metrics


def create_app(
    settings: Settings | None = None,
    *,
    mongo_client: MongoClient[Any] | None = None,
    redis_client: Any | None = None,
    ensure_indexes: bool = False,
) -> Flask:
    """Create and configure the Flask REST API application."""
    cfg = settings or get_settings()
    configure_logging(cfg.log_level)

    app = Flask(__name__)
    CORS(
        app,
        origins=cfg.allowed_origins,
        supports_credentials=False,
        allow_headers=["Authorization", "Content-Type", "X-API-Key", "Idempotency-Key", "If-Match"],
        methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    )

    container: Container = build_container(
        cfg,
        mongo_client=mongo_client,
        redis_client=redis_client,
        ensure_indexes=ensure_indexes,
    )
    app.extensions["container"] = container

    register_middleware(app, container)
    register_error_handlers(app)
    app.register_blueprint(create_v1_blueprint())

    @app.get("/health/live")
    def health_live() -> tuple[Response, int]:
        return jsonify({"status": "live"}), 200

    @app.get("/health/ready")
    def health_ready() -> tuple[Response, int]:
        mongo_ok = container.mongo.ping()
        redis_ok = container.redis.ping()
        ready = mongo_ok and redis_ok
        return jsonify(
            {"status": "ready" if ready else "degraded", "mongo": mongo_ok, "redis": redis_ok}
        ), (200 if ready else 503)

    @app.get("/metrics")
    def metrics() -> Response:
        token = cfg.metrics_auth_token
        if token:
            auth = request.headers.get("Authorization", "")
            provided = auth[7:].strip() if auth.startswith("Bearer ") else ""
            if not hmac.compare_digest(provided, token):
                raise AuthenticationError("Metrics authentication required")
        data, content_type = render_metrics()
        return Response(data, status=200, content_type=content_type)

    @app.get("/api/v1/openapi.json")
    def openapi_spec() -> tuple[Response, int]:
        return jsonify(build_openapi_spec(app)), 200

    return app


def run_api() -> None:
    cfg = get_settings()
    app = create_app(cfg, ensure_indexes=True)
    app.run(host=cfg.app_host, port=cfg.app_port)
