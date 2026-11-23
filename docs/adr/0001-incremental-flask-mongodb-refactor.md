# ADR-0001: Incremental Flask + MongoDB Refactor

- **Status:** Accepted
- **Date:** 2026-11-23
- **Deciders:** Engineering / Implementation Plan

## Context
The baseline repository is a Flask + Flask-RESTX + PyMongo application (`app.py`, `api/`). Moving directly to a different web framework (e.g. FastAPI) for REST would introduce unnecessary migration risk for existing `/api/*` compatibility shims. Meanwhile, MCP Streamable HTTP requires ASGI/Starlette compatibility, which the official Python `mcp` SDK provides directly.

## Decision
1. Keep **Flask** for the REST HTTP surface (`/api/v1/*` and gated legacy `/api/*` shims).
2. Introduce a clean layered package `data_collector/` (`domain`, `services`, `infrastructure`, `api`, `mcp`, `workers`).
3. Use **PyMongo** with a single centralized `MongoManager` per process and a single shared `records` collection with mandatory tenant scope predicates `(workspace_id, project_id, collection_id)`.
4. Run the **MCP Streamable HTTP** server (`dc-mcp-http`) as a dedicated process using the official `mcp` Python SDK, calling the exact same `data_collector.services` layer as Flask.
5. Keep `app.py` and `api/` as compatibility shims during migration, gated by configuration flags and deprecation headers, failing closed on unsafe legacy operations.

## Consequences
- Zero framework rewrite risk for REST endpoints.
- Clean separation of concerns: routes and MCP tools are thin adapters over shared services.
- Separate process entrypoints (`dc-api`, `dc-mcp-http`, `dc-mcp-stdio`, `dc-worker`) share one domain/service codebase.
