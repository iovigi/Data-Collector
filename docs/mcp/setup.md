# MCP Integration Guide (Claude & ChatGPT)

## 1. Local Stdio (Claude Desktop / Claude Code)
Create a least-privileged API key via `POST /api/v1/keys` with only required scopes (e.g. `workspace:read`, `collection:read`, `records:read`), then configure your local MCP client:

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

## 2. Remote Streamable HTTP (ChatGPT / Claude Custom Connector)
1. Deploy `dc-mcp-http` behind an HTTPS reverse proxy at `https://YOUR_DOMAIN/mcp`.
2. Ensure `MCP_PUBLIC_URL=https://YOUR_DOMAIN/mcp`, `AUTH_ISSUER`, `AUTH_AUDIENCE`, and `ALLOWED_ORIGINS` (including `https://chatgpt.com` and `https://claude.ai`) are configured.
3. Discovery endpoints:
   - `GET /.well-known/oauth-protected-resource`
   - `GET /.well-known/oauth-authorization-server`
4. Keep `MCP_ALLOW_WRITES=false` unless write tools are explicitly authorized.
5. Destructive deletes always require two steps: `dc_prepare_delete_record` -> `dc_delete_record`.
