# Operations Runbook — Data Collector 2.0

## 1. Initial Bootstrap
```bash
data-collector ensure-indexes
data-collector admin bootstrap --email admin@example.com
```

## 2. Running Services
- **REST API**: `dc-api` (or `gunicorn --bind 0.0.0.0:8000 --workers 2 --threads 4 "data_collector.app:create_app()"`)
- **RQ Worker**: `dc-worker`
- **MCP Remote HTTP**: `dc-mcp-http` (listen `0.0.0.0:8001`, terminate TLS at reverse proxy)
- **MCP Local Stdio**: `DATA_COLLECTOR_API_KEY=<key> dc-mcp-stdio`

## 3. Legacy Data Migration
```bash
# Dry run first
data-collector migrate-legacy --workspace-id <wid> --project-id <pid> --source-collection users --target-collection-id <cid> --dry-run
# Apply migration
data-collector migrate-legacy --workspace-id <wid> --project-id <pid> --source-collection users --target-collection-id <cid> --apply
```

## 4. Backup & Restore Drill (MongoDB)
```bash
# Backup
mongodump --uri="$MONGODB_URI" --db="$MONGODB_DB" --archive=backup.archive.gz --gzip
# Restore to rehearsal DB
mongorestore --uri="$MONGODB_URI" --nsFrom="${MONGODB_DB}.*" --nsTo="dc_rehearsal.*" --archive=backup.archive.gz --gzip
```

## 5. Emergency Rollback
- Disable `/mcp` ingress at reverse proxy while REST `/api/v1` continues.
- Revoke compromised API keys via `POST /api/v1/keys/{kid}/revoke`.
- Redeploy previous immutable container tag if needed.

## 6. Deleting a collection

Admin UI: open the collection (Data Explorer) → **Delete collection** (visible to owner/admin only) → check the counts → type the slug → Delete.

API (owner or admin token; an unrestricted API key with `collection:delete` also works):

```bash
CID=<collection id>
curl -s -X POST -H "Authorization: Bearer $TOKEN" https://data.devart.solutions/api/v1/collections/$CID/prepare-delete | tee prep.json
# read slug + records.total in prep.json, then:
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"confirmation_token\": \"$(jq -r .confirmation_token prep.json)\", \"confirm_slug\": \"$(jq -r .slug prep.json)\"}" \
  https://data.devart.solutions/api/v1/collections/$CID
```

The token lasts 5 minutes and is single-use. Check the audit log for `collection.delete` afterwards. Take a backup first (§4): this is a hard delete.
