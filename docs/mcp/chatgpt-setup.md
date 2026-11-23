# ChatGPT & OpenAI API MCP Setup

1. Deploy `dc-mcp-http` behind HTTPS using Caddy (`compose.yaml` `--profile tls`) at `https://YOUR_DOMAIN/mcp`.
2. Set `MCP_PUBLIC_URL=https://YOUR_DOMAIN/mcp`, `ALLOWED_ORIGINS=https://chatgpt.com`, and `OAUTH_MODE=external` (recommended) or `OAUTH_MODE=builtin`.
3. Verify discovery before connecting:
   - `curl -i https://YOUR_DOMAIN/.well-known/oauth-protected-resource`
   - `curl -i https://YOUR_DOMAIN/.well-known/oauth-authorization-server`
4. In ChatGPT Settings -> Connectors -> Custom Connector, enter `https://YOUR_DOMAIN/mcp` and complete OAuth 2.1 PKCE authorization.
5. **Note:** ChatGPT custom connector availability depends on your OpenAI plan/workspace policy. Republish connector tool snapshots if tool schemas change.
