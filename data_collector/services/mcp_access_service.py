"""MCP connection management for the admin: personal access tokens, connected OAuth
clients (grants), the values a client needs to connect, and an outside-in reachability
check.

Token design decision: MCP personal access tokens are a separate credential kind
(`dcp_<hex>.<secret>`, kind="mcp_pat") stored with the hashed workspace keys rather than
re-using workspace API keys (`dc_...`) on /mcp:
- a PAT belongs to one user and one workspace and is read-only unless the user opts in;
  producer API keys are usually shared ingest credentials with records:write;
- /mcp accepts PATs as `Authorization: Bearer`, REST rejects them (and /mcp rejects
  workspace keys as Bearer), so leaking one does not open the other surface;
- revoking or listing a person's AI connections never touches ingestion keys.
"""

from __future__ import annotations

import json
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from data_collector.config import Settings
from data_collector.domain.entities import serialize_value
from data_collector.domain.exceptions import AuthorizationError, NotFoundError, ValidationError
from data_collector.domain.identities import Actor, PrincipalType, Scope
from data_collector.domain.policies import effective_scopes, require_workspace_membership
from data_collector.infrastructure.crypto import hash_token
from data_collector.infrastructure.oauth import (
    DEFAULT_CLIENT_SCOPES,
    MCP_OAUTH_SCOPES,
    WRITE_OAUTH_SCOPES,
    OAuthService,
)
from data_collector.infrastructure.repositories.tenant_repo import (
    ApiKeyRepository,
    UserRepository,
    WorkspaceRepository,
)
from data_collector.services.audit_service import AuditService

MCP_TOKEN_MAX_DAYS = 365
_PROBE_TIMEOUT = 8.0


def generate_mcp_token() -> tuple[str, str, str]:
    """(plaintext, prefix, sha256) for an MCP personal access token."""
    prefix = f"dcp_{secrets.token_hex(4)}"
    plaintext = f"{prefix}.{secrets.token_urlsafe(32)}"
    return plaintext, prefix, hash_token(plaintext)


class McpAccessService:
    def __init__(
        self,
        *,
        settings: Settings,
        workspaces: WorkspaceRepository,
        api_keys: ApiKeyRepository,
        users: UserRepository,
        oauth: OAuthService,
        audit: AuditService,
    ) -> None:
        self._settings = settings
        self._workspaces = workspaces
        self._api_keys = api_keys
        self._users = users
        self._oauth = oauth
        self._audit = audit
        self._tool_names: list[str] | None = None

    # ── helpers ───────────────────────────────────────────────────────────────
    def _member(self, actor: Actor, workspace_id: str) -> frozenset[Scope]:
        role_str = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        role = require_workspace_membership(actor, workspace_id, role_str, Scope.WORKSPACE_READ)
        return effective_scopes(actor, role)

    @staticmethod
    def _require_session(actor: Actor) -> None:
        # Minting or listing personal credentials is for a signed-in person, not for a key.
        if actor.principal_type != PrincipalType.USER or actor.is_mcp or actor.key_id:
            raise AuthorizationError("Sign in to the admin to manage MCP connections")

    def tool_names(self) -> list[str]:
        """Names of the tools the MCP server actually registers (built once, lazily)."""
        if self._tool_names is None:
            from data_collector.mcp.tools import list_tool_names

            self._tool_names = list_tool_names()
        return list(self._tool_names)

    def _base_url(self) -> str:
        return self._settings.mcp_public_url.removesuffix("/mcp").rstrip("/")

    # ── connection info ───────────────────────────────────────────────────────
    def connection_info(self, actor: Actor, workspace_id: str) -> dict[str, Any]:
        self._member(actor, workspace_id)
        ws = self._workspaces.get_by_id(workspace_id)
        if ws is None:
            raise NotFoundError("Workspace not found")
        base = self._base_url()
        builtin = self._settings.oauth_mode == "builtin"
        return {
            "mcp_url": self._settings.mcp_public_url,
            "server_name": "data-collector",
            "workspace": {"id": ws["id"], "slug": ws["slug"], "name": ws["name"]},
            "oauth": {
                "mode": self._settings.oauth_mode,
                "protected_resource_metadata": f"{base}/.well-known/oauth-protected-resource",
                "authorization_server_metadata": (
                    f"{base}/.well-known/oauth-authorization-server"
                    if builtin
                    else f"{self._settings.auth_issuer.rstrip('/')}"
                    "/.well-known/oauth-authorization-server"
                ),
                "registration_endpoint": f"{base}/oauth/register" if builtin else None,
                "token_endpoint": f"{base}/oauth/token" if builtin else None,
                "dynamic_client_registration": builtin,
                "pkce": "S256",
            },
            "writes_enabled": self._settings.mcp_allow_writes,
            "default_scopes": list(DEFAULT_CLIENT_SCOPES),
            "available_scopes": list(MCP_OAUTH_SCOPES),
            "tools": self.tool_names(),
            "token_prefix": "dcp_",
        }

    # ── personal access tokens ────────────────────────────────────────────────
    def create_token(
        self,
        actor: Actor,
        workspace_id: str,
        *,
        name: str,
        scopes: list[str] | None = None,
        expires_in_days: int = 90,
    ) -> dict[str, Any]:
        self._require_session(actor)
        granted = self._member(actor, workspace_id)
        name = (name or "").strip()
        if not name or len(name) > 120:
            raise ValidationError("Token name must be 1-120 characters")
        if not 1 <= expires_in_days <= MCP_TOKEN_MAX_DAYS:
            raise ValidationError(f"expires_in_days must be 1-{MCP_TOKEN_MAX_DAYS}")
        requested = list(dict.fromkeys(scopes or DEFAULT_CLIENT_SCOPES))
        unknown = [s for s in requested if s not in MCP_OAUTH_SCOPES]
        if unknown:
            raise ValidationError(f"Unsupported MCP scope(s): {', '.join(unknown)}")
        beyond_role = [s for s in requested if Scope(s) not in granted]
        if beyond_role:
            raise AuthorizationError(f"Your role does not allow scope(s): {', '.join(beyond_role)}")
        plaintext, prefix, key_hash = generate_mcp_token()
        meta = self._api_keys.create(
            workspace_id=workspace_id,
            principal_id=actor.principal_id,
            name=name,
            prefix=prefix,
            key_hash=key_hash,
            scopes=requested,
            allowed_collection_ids=None,
            expires_at=datetime.now(UTC) + timedelta(days=expires_in_days),
            kind="mcp_pat",
        )
        self._audit.record(
            tenant=workspace_id,
            actor_id=actor.principal_id,
            action="mcp_token.create",
            target=f"key:{meta['id']}",
            decision="allow",
            metadata={"name": name, "scopes": requested, "prefix": prefix},
        )
        return {
            **meta,
            "token": plaintext,
            "read_only": not any(s in WRITE_OAUTH_SCOPES for s in requested),
            "writes_effective": self._settings.mcp_allow_writes
            and any(s in WRITE_OAUTH_SCOPES for s in requested),
        }

    def _can_manage(self, granted: frozenset[Scope]) -> bool:
        return Scope.WORKSPACE_MANAGE in granted

    def list_tokens(self, actor: Actor, workspace_id: str) -> list[dict[str, Any]]:
        self._require_session(actor)
        granted = self._member(actor, workspace_id)
        owner = None if self._can_manage(granted) else actor.principal_id
        items = self._api_keys.list_mcp_tokens(workspace_id, owner)
        return [i for i in items if i.get("revoked_at") is None]

    def revoke_token(self, actor: Actor, workspace_id: str, token_id: str) -> dict[str, Any]:
        self._require_session(actor)
        granted = self._member(actor, workspace_id)
        doc = self._api_keys.get_in_workspace(workspace_id, token_id)
        if doc is None or doc.get("kind") != "mcp_pat":
            raise NotFoundError("MCP token not found")
        if str(doc["principal_id"]) != actor.principal_id and not self._can_manage(granted):
            raise AuthorizationError("You can only revoke your own MCP tokens")
        res = self._api_keys.revoke(workspace_id, token_id)
        self._audit.record(
            tenant=workspace_id,
            actor_id=actor.principal_id,
            action="mcp_token.revoke",
            target=f"key:{token_id}",
            decision="allow",
        )
        return res or {}

    # ── connected clients (OAuth grants) ──────────────────────────────────────
    def list_grants(self, actor: Actor, workspace_id: str) -> list[dict[str, Any]]:
        self._require_session(actor)
        granted = self._member(actor, workspace_id)
        user = None if self._can_manage(granted) else actor.principal_id
        rows = self._oauth.list_grants(workspace_id=workspace_id, user_id=user)
        return [{k: serialize_value(v) for k, v in r.items()} for r in rows]

    def revoke_grant(self, actor: Actor, workspace_id: str, grant_id: str) -> None:
        self._require_session(actor)
        granted = self._member(actor, workspace_id)
        grant = self._oauth.get_grant(grant_id)
        if grant is None or grant.get("workspace_id") != workspace_id:
            raise NotFoundError("Connection not found")
        if str(grant.get("user_id")) != actor.principal_id and not self._can_manage(granted):
            raise AuthorizationError("You can only disconnect your own clients")
        self._oauth.revoke_grant(grant_id)
        self._audit.record(
            tenant=workspace_id,
            actor_id=actor.principal_id,
            action="oauth.grant_revoke",
            target=f"oauth_client:{grant.get('client_id')}",
            decision="allow",
            metadata={"client_name": grant.get("client_name"), "grant_user": grant.get("user_id")},
        )

    # ── outside-in connection check ───────────────────────────────────────────
    def connection_check(
        self, actor: Actor, workspace_id: str, *, http_client: httpx.Client | None = None
    ) -> dict[str, Any]:
        """Call this server's PUBLIC URLs (as a remote client would) and report each step.

        URLs come only from MCP_PUBLIC_URL / AUTH_ISSUER settings, never from the request,
        so this is not an SSRF vector.
        """
        self._require_session(actor)
        self._member(actor, workspace_id)
        info = self.connection_info(actor, workspace_id)
        client = http_client or httpx.Client(timeout=_PROBE_TIMEOUT, follow_redirects=False)
        checks: list[dict[str, Any]] = []

        def step(name: str, fn: Any) -> Any:
            t0 = time.perf_counter()
            try:
                ok, detail, value = fn()
            except Exception as exc:  # network errors are reported, not raised
                ok, detail, value = False, f"{type(exc).__name__}: {exc}"[:300], None
            checks.append(
                {
                    "check": name,
                    "ok": bool(ok),
                    "detail": detail,
                    "ms": round((time.perf_counter() - t0) * 1000),
                }
            )
            return value

        def prm() -> tuple[bool, str, Any]:
            r = client.get(info["oauth"]["protected_resource_metadata"])
            body = r.json() if r.status_code == 200 else {}
            ok = r.status_code == 200 and body.get("resource", "").rstrip("/") == info[
                "mcp_url"
            ].rstrip("/")
            return ok, f"HTTP {r.status_code}, resource={body.get('resource')}", body

        def asm() -> tuple[bool, str, Any]:
            r = client.get(info["oauth"]["authorization_server_metadata"])
            body = r.json() if r.status_code == 200 else {}
            need = ("authorization_endpoint", "token_endpoint")
            ok = r.status_code == 200 and all(body.get(k) for k in need)
            return ok, f"HTTP {r.status_code}, issuer={body.get('issuer')}", body

        def token_ep(as_meta: dict[str, Any]) -> tuple[bool, str, Any]:
            url = as_meta.get("token_endpoint")
            if not url:
                return False, "no token_endpoint in metadata", None
            r = client.post(url, data={"grant_type": "authorization_code", "code": "probe"})
            ok = r.status_code == 400 and "error" in r.text
            return ok, f"HTTP {r.status_code} (expected 400 invalid_grant)", None

        def unauth() -> tuple[bool, str, Any]:
            r = client.post(
                info["mcp_url"],
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                headers={"Accept": "application/json, text/event-stream"},
            )
            challenge = r.headers.get("www-authenticate", "")
            ok = r.status_code == 401 and "resource_metadata" in challenge
            return ok, f"HTTP {r.status_code}, WWW-Authenticate present={bool(challenge)}", None

        def tools() -> tuple[bool, str, Any]:
            if self._settings.oauth_mode != "builtin":
                return False, "skipped: external OAuth mode (no local token to probe with)", None
            user = self._users.find_by_id(actor.principal_id)
            token = self._oauth.mint_probe_token(
                user_id=actor.principal_id,
                email=str((user or {}).get("email", "")),
                workspace_id=workspace_id,
            )
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            }
            init = client.post(
                info["mcp_url"],
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "dc-connection-check", "version": "1"},
                    },
                },
            )
            if init.status_code != 200:
                return False, f"initialize HTTP {init.status_code}", None
            sid = init.headers.get("mcp-session-id")
            if sid:
                headers["Mcp-Session-Id"] = sid
            client.post(
                info["mcp_url"],
                headers=headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            r = client.post(
                info["mcp_url"],
                headers=headers,
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            )
            payload = _jsonrpc_payload(r.text)
            names = [t.get("name") for t in (payload.get("result") or {}).get("tools", [])]
            ok = r.status_code == 200 and "dc_aggregate" in names
            return ok, f"HTTP {r.status_code}, {len(names)} tools", names

        step("Protected resource metadata", prm)
        as_meta = step("Authorization server metadata", asm) or {}
        step("Token endpoint", lambda: token_ep(as_meta))
        step("MCP endpoint asks for sign-in", unauth)
        tool_names = step("Tool listing", tools) or []
        if http_client is None:
            client.close()
        self._audit.record(
            tenant=workspace_id,
            actor_id=actor.principal_id,
            action="mcp.connection_check",
            target=f"mcp:{info['mcp_url']}",
            decision="allow" if all(c["ok"] for c in checks) else "error",
            metadata={"failed": [c["check"] for c in checks if not c["ok"]]},
        )
        return {
            "mcp_url": info["mcp_url"],
            "ok": all(c["ok"] for c in checks),
            "checks": checks,
            "tools": tool_names,
        }


def _jsonrpc_payload(text: str) -> dict[str, Any]:
    """Parse a JSON-RPC response sent as plain JSON or as an SSE `data:` line."""
    text = text.strip()
    if text.startswith("{"):
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}
    for line in text.splitlines():
        if line.startswith("data:"):
            try:
                data = json.loads(line[5:].strip())
                if isinstance(data, dict):
                    return data
            except ValueError:
                continue
    return {}
