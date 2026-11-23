"""Authentication, JWT lifecycle, API key, and CLI bootstrap service."""

from __future__ import annotations

import contextlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from data_collector.config import Settings
from data_collector.domain.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from data_collector.domain.identities import Actor, PrincipalType, Scope
from data_collector.domain.policies import require_workspace_membership
from data_collector.infrastructure.crypto import (
    generate_api_key,
    hash_password,
    hash_token,
    verify_password,
    verify_token_hash,
)
from data_collector.infrastructure.redis import RateLimiter
from data_collector.infrastructure.repositories.tenant_repo import (
    ApiKeyRepository,
    RefreshTokenRepository,
    UserRepository,
    WorkspaceRepository,
)
from data_collector.services.audit_service import AuditService


class AuthService:
    def __init__(
        self,
        *,
        settings: Settings,
        users: UserRepository,
        workspaces: WorkspaceRepository,
        api_keys: ApiKeyRepository,
        refresh_tokens: RefreshTokenRepository,
        audit: AuditService,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self._settings = settings
        self._users = users
        self._workspaces = workspaces
        self._api_keys = api_keys
        self._refresh_tokens = refresh_tokens
        self._audit = audit
        self._rate_limiter = rate_limiter

    def bootstrap_admin(self, email: str, password: str) -> dict[str, Any]:
        """Explicit CLI-only admin creation. Never resets an existing user's password."""
        if len(password) < 12:
            raise ValidationError("Admin password must be at least 12 characters")
        existing = self._users.find_by_email(email)
        if existing is not None:
            raise ConflictError("User already exists; refusing to reset password")
        pw_hash = hash_password(password)
        user = self._users.create(email, pw_hash, is_superadmin=True)
        self._audit.record(
            tenant=None,
            actor_id=user["id"],
            action="admin.bootstrap",
            target=f"user:{user['id']}",
            decision="allow",
        )
        return {"id": user["id"], "email": user["email"]}

    def register_user(self, email: str, password: str) -> dict[str, Any]:
        if len(password) < 12:
            raise ValidationError("Password must be at least 12 characters")
        pw_hash = hash_password(password)
        user = self._users.create(email, pw_hash)
        return {"id": user["id"], "email": user["email"]}

    def login(self, email: str, password: str, *, client_ip: str = "unknown") -> dict[str, Any]:
        """Authenticate local user with rate limiting and uniform 401 failure."""
        if self._rate_limiter is not None:
            self._rate_limiter.check(
                f"login:{client_ip}:{email.strip().lower()}",
                self._settings.rate_limit_login_per_minute,
                is_mutation=True,
            )

        user = self._users.find_by_email(email)
        if user is None or user.get("status") != "active":
            self._audit.record(
                tenant=None,
                actor_id="anonymous",
                action="auth.login",
                target="local",
                decision="deny",
            )
            raise AuthenticationError("Invalid credentials")

        valid, needs_rehash = verify_password(password, str(user.get("password_hash", "")))
        if not valid:
            self._audit.record(
                tenant=None,
                actor_id=str(user["_id"]),
                action="auth.login",
                target=f"user:{user['_id']}",
                decision="deny",
            )
            raise AuthenticationError("Invalid credentials")

        user_id = str(user["_id"])
        if needs_rehash:
            self._users.update_password_hash(user_id, hash_password(password))

        access_token = self._issue_access_token(user_id=user_id, email=str(user["email"]))
        refresh_token = self._issue_refresh_token(user_id=user_id, family_id=secrets.token_hex(12))

        self._audit.record(
            tenant=None,
            actor_id=user_id,
            action="auth.login",
            target=f"user:{user_id}",
            decision="allow",
        )
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "expires_in": self._settings.access_token_ttl_seconds,
        }

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        """Atomically rotate refresh token with replay detection."""
        token_hash = hash_token(refresh_token)
        record = self._refresh_tokens.consume_if_active(token_hash)
        if record is None:
            existing = self._refresh_tokens.find_by_hash(token_hash)
            if existing is not None and existing.get("revoked_at") is not None:
                self._refresh_tokens.revoke_family(str(existing["family_id"]))
                raise AuthenticationError("Refresh token reused; session revoked")
            raise AuthenticationError("Invalid refresh token")

        expires_at = record["expires_at"]
        if isinstance(expires_at, datetime):
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at < datetime.now(UTC):
                raise AuthenticationError("Refresh token expired")

        user_id = str(record["user_id"])
        user = self._users.find_by_id(user_id)
        if user is None or user.get("status") != "active":
            raise AuthenticationError("Account unavailable")

        new_access = self._issue_access_token(user_id=user_id, email=str(user["email"]))
        new_refresh = self._issue_refresh_token(
            user_id=user_id,
            family_id=str(record["family_id"]),
        )
        return {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "token_type": "Bearer",
            "expires_in": self._settings.access_token_ttl_seconds,
        }

    def logout(self, refresh_token: str) -> None:
        token_hash = hash_token(refresh_token)
        record = self._refresh_tokens.find_by_hash(token_hash)
        if record is not None:
            self._refresh_tokens.revoke_family(str(record["family_id"]))

    def authenticate_bearer(self, token: str, *, is_mcp: bool = False) -> Actor:
        """Verify JWT access token and return Actor."""
        try:
            payload = jwt.decode(
                token,
                self._settings.jwt_secret_key,
                algorithms=["HS256"],
                audience=self._settings.auth_audience,
                issuer=self._settings.auth_issuer,
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError("Invalid or expired token") from exc

        sub = payload.get("sub")
        if not isinstance(sub, str) or not sub:
            raise AuthenticationError("Token missing subject")

        scopes: frozenset[Scope] | None = None
        raw_scopes = payload.get("scopes")
        if isinstance(raw_scopes, list):
            parsed: set[Scope] = set()
            for s in raw_scopes:
                with contextlib.suppress(ValueError):
                    parsed.add(Scope(s))
            scopes = frozenset(parsed)

        return Actor(
            principal_id=sub,
            principal_type=PrincipalType.OAUTH_CLIENT
            if payload.get("client_id")
            else PrincipalType.USER,
            email=payload.get("email"),
            scopes=scopes,
            workspace_id=payload.get("workspace_id"),
            client_id=payload.get("client_id"),
            is_mcp=is_mcp,
            mcp_allow_writes=self._settings.mcp_allow_writes,
        )

    def authenticate_api_key(self, raw_key: str, *, is_mcp: bool = False) -> Actor:
        """Verify prefixed API key (`dc_<hex>.<secret>`) and return scoped Actor."""
        if "." not in raw_key:
            raise AuthenticationError("Invalid API key format")
        prefix, _ = raw_key.split(".", 1)
        doc = self._api_keys.find_by_prefix(prefix)
        if doc is None or not verify_token_hash(raw_key, str(doc.get("key_hash", ""))):
            raise AuthenticationError("Invalid API key")
        if doc.get("revoked_at") is not None:
            raise AuthenticationError("API key revoked")
        expires_at = doc.get("expires_at")
        if isinstance(expires_at, datetime):
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at < datetime.now(UTC):
                raise AuthenticationError("API key expired")

        self._api_keys.touch_last_used(doc["_id"])
        scopes = frozenset(Scope(s) for s in doc.get("scopes", []) if s in Scope._value2member_map_)
        raw_allowed = doc.get("allowed_collection_ids")
        allowed_cols = (
            frozenset(str(c) for c in raw_allowed) if isinstance(raw_allowed, list) else None
        )
        return Actor(
            principal_id=str(doc["principal_id"]),
            principal_type=PrincipalType.API_KEY,
            scopes=scopes,
            workspace_id=str(doc["workspace_id"]),
            key_id=str(doc["_id"]),
            allowed_collection_ids=allowed_cols,
            is_mcp=is_mcp,
            mcp_allow_writes=self._settings.mcp_allow_writes,
        )

    def create_api_key(
        self,
        actor: Actor,
        *,
        workspace_id: str,
        name: str,
        scopes: list[str],
        allowed_collection_ids: list[str] | None = None,
        expires_in_days: int = 90,
    ) -> dict[str, Any]:
        role = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        require_workspace_membership(actor, workspace_id, role, Scope.KEYS_MANAGE)

        validated_scopes: list[str] = []
        for s in scopes:
            try:
                validated_scopes.append(Scope(s).value)
            except ValueError as exc:
                raise ValidationError(f"Unknown scope '{s}'") from exc

        plaintext, prefix, key_hash = generate_api_key()
        expires_at = datetime.now(UTC) + timedelta(days=expires_in_days)
        meta = self._api_keys.create(
            workspace_id=workspace_id,
            principal_id=actor.principal_id,
            name=name,
            prefix=prefix,
            key_hash=key_hash,
            scopes=validated_scopes,
            allowed_collection_ids=allowed_collection_ids,
            expires_at=expires_at,
        )
        self._audit.record(
            tenant=workspace_id,
            actor_id=actor.principal_id,
            action="api_key.create",
            target=f"key:{meta['id']}",
            decision="allow",
        )
        return {**meta, "api_key": plaintext}

    def list_api_keys(self, actor: Actor, workspace_id: str) -> list[dict[str, Any]]:
        role = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        require_workspace_membership(actor, workspace_id, role, Scope.KEYS_MANAGE)
        return self._api_keys.list_for_workspace(workspace_id)

    def revoke_api_key(self, actor: Actor, workspace_id: str, key_id: str) -> dict[str, Any]:
        role = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        require_workspace_membership(actor, workspace_id, role, Scope.KEYS_MANAGE)
        res = self._api_keys.revoke(workspace_id, key_id)
        if res is None:
            raise NotFoundError("API key not found")
        self._audit.record(
            tenant=workspace_id,
            actor_id=actor.principal_id,
            action="api_key.revoke",
            target=f"key:{key_id}",
            decision="allow",
        )
        return res

    def get_key_allowed_collections(self, actor: Actor) -> list[str] | None:
        if actor.key_id is None:
            return None
        # Look up by prefix/key_id if needed; for simplicity, only restrict when set
        return None

    def _issue_access_token(
        self,
        *,
        user_id: str,
        email: str | None = None,
        scopes: list[str] | None = None,
        client_id: str | None = None,
    ) -> str:
        now = datetime.now(UTC)
        payload: dict[str, Any] = {
            "sub": user_id,
            "iss": self._settings.auth_issuer,
            "aud": self._settings.auth_audience,
            "iat": int(now.timestamp()),
            "exp": int(
                (now + timedelta(seconds=self._settings.access_token_ttl_seconds)).timestamp()
            ),
            "jti": secrets.token_hex(12),
        }
        if email:
            payload["email"] = email
        if scopes is not None:
            payload["scopes"] = scopes
        if client_id:
            payload["client_id"] = client_id
        return jwt.encode(payload, self._settings.jwt_secret_key, algorithm="HS256")

    def _issue_refresh_token(self, *, user_id: str, family_id: str) -> str:
        raw = secrets.token_urlsafe(48)
        expires_at = datetime.now(UTC) + timedelta(seconds=self._settings.refresh_token_ttl_seconds)
        self._refresh_tokens.store(hash_token(raw), user_id, family_id, expires_at)
        return raw
