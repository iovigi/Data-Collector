"""Legacy Flask compatibility entrypoint (M1 hardened).

Default admin seeding on startup and hardcoded JWT fallback secrets have been removed.
Legacy /api/* routes are disabled by default unless ENABLE_LEGACY_API=true is explicitly set.
"""

from __future__ import annotations

import os
from datetime import timedelta

from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_restx import Api

from api.models.models import init_models
from api.models.user_model import init_login_model


def create_app() -> Flask:
    app = Flask(__name__)

    allowed_origins = [
        o.strip()
        for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
        if o.strip()
    ]
    CORS(app, origins=allowed_origins)

    jwt_secret = os.environ.get("JWT_SECRET_KEY", "").strip()
    weak = {"", "your-secret-key", "secret", "changeme"}
    if jwt_secret in weak or len(jwt_secret) < 32:
        raise RuntimeError(
            "JWT_SECRET_KEY must be set to a strong >=32-char secret before starting legacy app"
        )

    app.config["JWT_SECRET_KEY"] = jwt_secret
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(minutes=15)
    JWTManager(app)

    enable_legacy = os.environ.get("ENABLE_LEGACY_API", "false").lower() == "true"
    if not enable_legacy:
        @app.route("/api/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
        def _legacy_disabled(subpath: str):  # noqa: ARG001
            return (
                jsonify(
                    {
                        "error": {
                            "code": "LEGACY_API_DISABLED",
                            "message": "Legacy /api/* endpoints are disabled. Migrate to /api/v1/*.",
                        }
                    }
                ),
                410,
            )
        return app

    authorizations = {
        "Bearer Auth": {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
        }
    }
    api = Api(
        app,
        version="1.0-deprecated",
        title="Data Collector Legacy API (Deprecated)",
        authorizations=authorizations,
        security=["Bearer Auth"],
    )
    init_models(api)
    init_login_model(api)
    ns = api.namespace("api", description="Deprecated legacy endpoints")

    from api.routes.auth import Login
    from api.routes.delete import Delete
    from api.routes.index import CreateIndex
    from api.routes.insert import BulkInsert, Insert
    from api.routes.query import Query
    from api.routes.update import BulkUpdate, Update

    for cls in (Insert, BulkInsert, Query, Update, BulkUpdate, Delete, CreateIndex, Login):
        cls.init_api(api)

    ns.add_resource(Insert, "/insert")
    ns.add_resource(BulkInsert, "/bulk_insert")
    ns.add_resource(Query, "/query")
    ns.add_resource(Update, "/update")
    ns.add_resource(BulkUpdate, "/bulk_update")
    ns.add_resource(Delete, "/delete")
    ns.add_resource(CreateIndex, "/create_index")
    ns.add_resource(Login, "/login")

    @app.after_request
    def _deprecation_headers(resp):
        resp.headers["Deprecation"] = "true"
        resp.headers["Sunset"] = "2027-01-01"
        return resp

    return app


if __name__ == "__main__":
    create_app().run()
