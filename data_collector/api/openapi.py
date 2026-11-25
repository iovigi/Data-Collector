"""Complete OpenAPI 3.1.0 specification generator with Pydantic schemas & security schemes."""

from __future__ import annotations

import re
from typing import Any

from flask import Flask
from pydantic import BaseModel

from data_collector.api.schemas import (
    AddMemberRequest,
    AggregateRequest,
    BatchCreateRecordsRequest,
    CreateApiKeyRequest,
    CreateCollectionRequest,
    CreateProjectRequest,
    CreateRecordRequest,
    CreateWorkspaceRequest,
    DeleteCollectionRequest,
    DeleteRecordRequest,
    DistinctValuesRequest,
    HistogramRequest,
    LoginRequest,
    RefreshRequest,
    SearchRecordsRequest,
    UpdateCollectionRequest,
    UpdateRecordRequest,
)

_MODELS: list[type[BaseModel]] = [
    LoginRequest,
    RefreshRequest,
    CreateWorkspaceRequest,
    AddMemberRequest,
    CreateProjectRequest,
    CreateCollectionRequest,
    UpdateCollectionRequest,
    DeleteCollectionRequest,
    CreateRecordRequest,
    BatchCreateRecordsRequest,
    UpdateRecordRequest,
    DeleteRecordRequest,
    SearchRecordsRequest,
    CreateApiKeyRequest,
    AggregateRequest,
    DistinctValuesRequest,
    HistogramRequest,
]

_ENDPOINT_BODY_MAP: dict[str, str] = {
    "api_v1.auth_v1.login": "LoginRequest",
    "api_v1.auth_v1.refresh": "RefreshRequest",
    "api_v1.auth_v1.logout": "RefreshRequest",
    "api_v1.workspaces_v1.create_workspace": "CreateWorkspaceRequest",
    "api_v1.workspaces_v1.add_member": "AddMemberRequest",
    "api_v1.projects_v1.create_project": "CreateProjectRequest",
    "api_v1.collections_v1.create_collection": "CreateCollectionRequest",
    "api_v1.collections_v1.update_collection": "UpdateCollectionRequest",
    "api_v1.collections_v1.delete_collection": "DeleteCollectionRequest",
    "api_v1.records_v1.create_record": "CreateRecordRequest",
    "api_v1.records_v1.batch_create_records": "BatchCreateRecordsRequest",
    "api_v1.records_v1.update_record": "UpdateRecordRequest",
    "api_v1.records_v1.delete_record": "DeleteRecordRequest",
    "api_v1.records_v1.search_records": "SearchRecordsRequest",
    "api_v1.keys_v1.create_key": "CreateApiKeyRequest",
    "api_v1.analytics_v1.aggregate": "AggregateRequest",
    "api_v1.analytics_v1.distinct_values": "DistinctValuesRequest",
    "api_v1.analytics_v1.histogram": "HistogramRequest",
}

_PUBLIC_ENDPOINTS = frozenset(
    {"api_v1.auth_v1.login", "api_v1.auth_v1.refresh", "api_v1.auth_v1.logout"}
)


def build_openapi_spec(app: Flask) -> dict[str, Any]:
    """Generate a complete OpenAPI 3.1.0 document from Flask routes and Pydantic DTOs."""
    schemas: dict[str, Any] = {
        "ErrorEnvelope": {
            "type": "object",
            "required": ["error"],
            "properties": {
                "error": {
                    "type": "object",
                    "required": ["code", "message", "request_id"],
                    "properties": {
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "details": {"type": "array", "items": {"type": "object"}},
                        "request_id": {"type": "string"},
                    },
                }
            },
        }
    }
    for model in _MODELS:
        schemas[model.__name__] = model.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )

    paths: dict[str, Any] = {}
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        if not rule.rule.startswith("/api/v1") or rule.rule == "/api/v1/openapi.json":
            continue
        oa_path = re.sub(r"<(?:[^:]+:)?([^>]+)>", r"{\1}", rule.rule)
        path_params = [
            {"name": arg, "in": "path", "required": True, "schema": {"type": "string"}}
            for arg in sorted(rule.arguments)
        ]
        methods = sorted(m for m in (rule.methods or set()) if m not in {"HEAD", "OPTIONS"})
        path_item: dict[str, Any] = {}
        for m in methods:
            op: dict[str, Any] = {
                "operationId": rule.endpoint.replace(".", "_"),
                "responses": {
                    "200": {"description": "Success"},
                    "400": {
                        "description": "Bad Request",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ErrorEnvelope"}
                            }
                        },
                    },
                    "401": {
                        "description": "Unauthenticated",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ErrorEnvelope"}
                            }
                        },
                    },
                    "403": {
                        "description": "Forbidden",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ErrorEnvelope"}
                            }
                        },
                    },
                    "404": {
                        "description": "Not Found",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ErrorEnvelope"}
                            }
                        },
                    },
                    "422": {
                        "description": "Validation Error",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ErrorEnvelope"}
                            }
                        },
                    },
                    "429": {
                        "description": "Rate Limited",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ErrorEnvelope"}
                            }
                        },
                    },
                },
            }
            if path_params:
                op["parameters"] = path_params
            if rule.endpoint not in _PUBLIC_ENDPOINTS:
                op["security"] = [{"BearerAuth": []}, {"ApiKeyAuth": []}]
            body_model = _ENDPOINT_BODY_MAP.get(rule.endpoint)
            if body_model:
                op["requestBody"] = {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": f"#/components/schemas/{body_model}"}
                        }
                    },
                }
            path_item[m.lower()] = op
        paths[oa_path] = path_item

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Data Collector API",
            "version": "2.0.0",
            "description": "Multi-tenant data collection platform REST API v1.",
        },
        "components": {
            "securitySchemes": {
                "BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"},
                "ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
            },
            "schemas": schemas,
        },
        "paths": paths,
    }
