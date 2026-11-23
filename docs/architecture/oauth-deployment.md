# OAuth 2.1 & Remote MCP Architecture Decision Record

- **Status:** Accepted
- **Date:** 2026-11-23
- **Applies to:** `dc-mcp-http` (Streamable HTTP `/mcp`), ChatGPT Custom MCP Connectors, OpenAI Responses API MCP, Claude Remote Custom Connectors

## 1. Client Requirements Summary
Remote MCP clients (ChatGPT Connectors, OpenAI Responses API, Claude Remote Custom Connectors) discover authorization requirements via:
1. `401 Unauthorized` with `WWW-Authenticate: Bearer resource_metadata="<origin>/.well-known/oauth-protected-resource"`
2. `GET /.well-known/oauth-protected-resource` (RFC 9728) returning `resource` (exact `MCP_PUBLIC_URL`), `authorization_servers`, and `scopes_supported`.
3. `GET /.well-known/oauth-authorization-server` (RFC 8414) returning `authorization_endpoint`, `token_endpoint`, `revocation_endpoint`, `jwks_uri`, `registration_endpoint` (RFC 7591), `code_challenge_methods_supported: ["S256"]`, and `grant_types_supported: ["authorization_code", "refresh_token"]`.

## 2. Deployment Modes (`OAUTH_MODE`)
Data Collector 2.0 supports two explicit modes without ever advertising unimplemented endpoints:

### Mode A: `OAUTH_MODE=external` (Recommended for Production)
- Delegates interactive login, MFA, and consent to an external OIDC/OAuth 2.1 Identity Provider (e.g. Keycloak, Auth0, Okta, Microsoft Entra ID, Google).
- `/.well-known/oauth-protected-resource` points `authorization_servers` to the external `AUTH_ISSUER`.
- `dc-mcp-http` validates incoming Bearer tokens using RS256/ES256 signatures fetched from `AUTH_JWKS_URL` (via `PyJWKClient`), enforcing `iss == AUTH_ISSUER`, `aud == MCP_PUBLIC_URL`, `exp`, and `nbf`. Local HS256 JWTs are **not** accepted as external OAuth tokens.

### Mode B: `OAUTH_MODE=builtin` (Self-Hosted / CI Test Issuer)
- `dc-mcp-http` mounts real, standards-compliant OAuth 2.1 endpoints backed by MongoDB:
  - `GET /oauth/authorize` & `POST /oauth/authorize` (authenticates user credentials via `AuthService`, validates `redirect_uri`, `code_challenge_method=S256`, `resource`, and issues single-use authorization code)
  - `POST /oauth/token` (`authorization_code` with PKCE `S256` verification and `refresh_token` rotation)
  - `POST /oauth/revoke` (RFC 7009 token revocation)
  - `POST /oauth/register` (RFC 7591 dynamic client registration with strict redirect URI validation)
  - `GET /.well-known/jwks.json` (RS256 public key set)
- Access tokens are RS256-signed JWTs bound to `iss=AUTH_ISSUER` and `aud=MCP_PUBLIC_URL`.
- **No fake endpoints:** `/.well-known/oauth-authorization-server` is served directly by `dc-mcp-http` with exact reachable URLs matching the active mode.
