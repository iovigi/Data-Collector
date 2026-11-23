# Production Deployment, Storage & Backup Guide

## Topology
- `api` (`dc-api`): Flask REST API v1 on internal port `8000`.
- `mcp-http` (`dc-mcp-http`): Streamable HTTP MCP + OAuth 2.1 on internal port `8001`.
- `worker` (`dc-worker`): RQ background worker sharing `artifacts_data` volume (`/app/var/storage`) with `api`.
- `caddy`: TLS reverse proxy (`docker compose --profile tls up -d`) terminating HTTPS and routing `/mcp*`, `/.well-known/*`, `/oauth/*` to `mcp-http:8001` with `flush_interval -1`.

## Storage (`ArtifactStore`)
`LocalVolumeArtifactStore` stores imports/exports under `STORAGE_DIR` using opaque server-generated keys (`<workspace_id>/exports/<job_id>.<fmt>`) with path-traversal rejection and SHA-256 integrity verification. Mount a shared durable volume (`artifacts_data`) across `api` and `worker`.

## Backup & Restore
```bash
mongodump --uri="$MONGODB_URI" --db="$MONGODB_DB" --archive=dc-backup.archive.gz --gzip
tar -czf dc-artifacts.tar.gz -C /app/var/storage .
# Restore rehearsal:
mongorestore --uri="$MONGODB_URI" --nsFrom="${MONGODB_DB}.*" --nsTo="dc_rehearsal.*" --archive=dc-backup.archive.gz --gzip
```
