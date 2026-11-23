# Claude Desktop, Claude Code & Claude Remote Setup

## Local Stdio (Claude Code / Claude Desktop)
```json
{
  "mcpServers": {
    "data-collector": {
      "command": "dc-mcp-stdio",
      "env": {
        "MONGODB_URI": "mongodb://localhost:27017/",
        "MONGODB_DB": "data_collector",
        "REDIS_URL": "redis://localhost:6379/0",
        "DATA_COLLECTOR_API_KEY": "dc_xxxx.yyyy"
      }
    }
  }
}
```
MCP runs in read-only mode by default (`MCP_ALLOW_WRITES=false`).

## Remote Custom Connector (Claude.ai)
1. Expose `dc-mcp-http` over HTTPS at `https://YOUR_DOMAIN/mcp` with `ALLOWED_ORIGINS=https://claude.ai`.
2. Add `https://YOUR_DOMAIN/mcp` in Claude Custom Connectors and complete OAuth 2.1 PKCE consent.
3. For destructive deletes when `MCP_ALLOW_WRITES=true`, the server requires `dc_prepare_delete_record` -> `dc_delete_record` with a one-time signed token.
