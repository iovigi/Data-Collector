# Target State Architecture (Data Collector 2.0)

## 1. High-Level Architecture
Data Collector 2.0 is a multi-tenant, API-first data collection and workspace platform with REST API v1, async Redis/RQ background workers, and Model Context Protocol (MCP) integrations (stdio and Streamable HTTP with OAuth 2.1).

```text
ChatGPT / OpenAI API     Claude / Claude Desktop     CLI / SDK Clients
         |                          |                        |
         +------- HTTPS /mcp -------+                        |
                       |                            local stdio MCP
                  MCP Gateway                                |
                       +---------------+---------------------+
                                       |
                          Auth + Policy Engine (RBAC/Scopes)
                                       |
REST /api/v1 ---> Flask API ---> Application Services <--- RQ Worker
                                       |
                          Repositories + JSON Schema + Query AST
                                  |                  |
                               MongoDB             Redis
```

## 2. Core Architectural Boundaries
- **Hard Boundary**: Neither Flask routes nor MCP tools may call PyMongo directly. All data access flows through `data_collector.services.*` -> `data_collector.infrastructure.repositories.*`.
- **Shared Storage Model**: User records reside in a single `records` MongoDB collection with mandatory indexed `(workspace_id, project_id, collection_id, deleted_at, _id)` scope filters injected at the repository layer. No user input can select a physical MongoDB collection name.
- **Authentication & Authorization**:
  - Human users authenticate via JWT (short-lived access + rotating refresh tokens) or OIDC/OAuth 2.1.
  - Service accounts and CLI/MCP local clients use scoped, prefixed, hashed API keys (`dc_live_<prefix>_<secret>`).
  - Enforcement order: `authenticate -> resolve workspace/project -> verify membership & scope -> collection policy -> validate arguments -> repository tenant filter -> audit event`.
- **Safe Query DSL**: Structured AST (`and`/`or`/`not` with depth <= 4, branches <= 20, allowlisted operators `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `exists`, `contains`) compiled to safe MongoDB predicates against schema-allowlisted fields only.
- **Async Jobs**: Redis + RQ worker (`dc-worker`) processes CSV/JSON/JSONL imports and exports with MongoDB `jobs` collection as authoritative state.
- **MCP Integration**: Official `mcp` Python SDK exposing `dc-mcp-stdio` and `dc-mcp-http` (Streamable HTTP `/mcp` + OAuth 2.1 metadata). Read-only by default; destructive deletes require `dc_prepare_delete_record` intent token + `dc_delete_record`.
