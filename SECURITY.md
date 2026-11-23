# Security Policy

## Reporting a Vulnerability
Please report security issues privately to the repository maintainers rather than opening a public issue.

## Security Controls in Data Collector 2.0
- **Fail-fast configuration**: Production startup fails if `JWT_SECRET_KEY` is weak/missing or `ALLOWED_ORIGINS` is wildcarded.
- **Explicit bootstrap**: Initial admin accounts are created only via `data-collector admin bootstrap`.
- **Tenant isolation**: All records are stored in `records` with mandatory `(workspace_id, project_id, collection_id)` repository predicates.
- **NoSQL injection defense**: Only the Safe Query DSL AST is accepted; raw MongoDB operators are rejected.
- **MCP safety**: Read-only by default; destructive deletes require a one-time server-signed confirmation token (`dc_prepare_delete_record`).
