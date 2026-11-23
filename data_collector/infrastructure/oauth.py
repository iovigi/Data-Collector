"""Standards-compliant OAuth 2.1 provider & verifier (PKCE S256, RS256 JWKS, refresh rotation)."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWKClient
from pymongo.database import Database

from data_collector.config import Settings
from data_collector.domain.exceptions import AuthenticationError, BadRequestError, ValidationError
from data_collector.domain.identities import Actor, PrincipalType, Scope
from data_collector.infrastructure.crypto import hash_token

SUPPORTED_OAUTH_SCOPES: frozenset[str] = frozenset(s.value for s in Scope)
DEFAULT_CLIENT_SCOPES: list[str] = ["workspace:read", "collection:read", "records:read"]


def _b64url_uint(val: int) -> str:
    raw = val.to_bytes((val.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def verify_pkce_s256(code_verifier: str, code_challenge: str) -> bool:
    """Verify RFC 7636 PKCE S256 challenge."""
    if not code_verifier or len(code_verifier) < 43 or len(code_verifier) > 128:
        return False
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    computed = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return secrets.compare_digest(computed, code_challenge)


def validate_redirect_uri(uri: str, *, allow_localhost_dev: bool = True) -> str:
    """Validate OAuth redirect URI (strict scheme, no fragments/wildcards/userinfo)."""
    if not uri or "*" in uri or "#" in uri or any(ord(c) > 127 for c in uri):
        raise ValidationError("Invalid redirect_uri syntax")
    parsed = urlparse(uri)
    if parsed.username or parsed.password:
        raise ValidationError("redirect_uri must not contain userinfo")
    if parsed.scheme == "https" and parsed.netloc and parsed.hostname:
        return uri
    if (
        allow_localhost_dev
        and parsed.scheme == "http"
        and parsed.hostname in {"localhost", "127.0.0.1"}
    ):
        return uri
    raise ValidationError("redirect_uri must use https (or http://localhost in dev/test)")


def parse_and_validate_scopes(raw_scope: str) -> list[str]:
    """Parse space-delimited scope string and reject any unknown scope."""
    scopes = [s.strip() for s in raw_scope.split() if s.strip()]
    if not scopes:
        return list(DEFAULT_CLIENT_SCOPES)
    for s in scopes:
        if s not in SUPPORTED_OAUTH_SCOPES:
            raise BadRequestError(f"Unknown OAuth scope '{s}'")
    return list(dict.fromkeys(scopes))


class OAuthService:
    """Builtin OAuth 2.1 provider and RS256/JWKS token verifier."""

    def __init__(self, settings: Settings, db: Database[Any]) -> None:
        self._settings = settings
        self._db = db
        self._clients = db.oauth_clients
        self._codes = db.oauth_codes
        self._refresh_tokens = db.oauth_refresh_tokens
        self._revoked = db.oauth_revoked_jtis
        self._jwk_client: PyJWKClient | None = None

        self._private_key: rsa.RSAPrivateKey | None = None
        self._public_key: rsa.RSAPublicKey | None = None
        self._kid: str | None = None

        if settings.oauth_mode == "external":
            if settings.oauth_jwks_url:
                self._jwk_client = PyJWKClient(settings.oauth_jwks_url)
        else:
            if settings.oauth_rsa_private_key_pem.strip():
                self._private_key = self._load_signing_key(settings.oauth_rsa_private_key_pem)
            elif settings.app_env == "production":
                raise ValueError(
                    "OAUTH_RSA_PRIVATE_KEY_PEM is required in production when OAUTH_MODE=builtin"
                )
            else:
                self._private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

            self._public_key = self._private_key.public_key()
            pub_pem = self._public_key.public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            self._kid = hashlib.sha256(pub_pem).hexdigest()[:16]

    @staticmethod
    def _load_signing_key(pem_str: str) -> rsa.RSAPrivateKey:
        pem_bytes = pem_str.replace("\\n", "\n").encode("utf-8")
        key = serialization.load_pem_private_key(pem_bytes, password=None)
        if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
            raise ValueError("OAUTH_RSA_PRIVATE_KEY_PEM must be an RSA key >= 2048 bits")
        return key

    def jwks(self) -> dict[str, Any]:
        """Return RFC 7517 JWKS containing the active RS256 public key."""
        if self._public_key is None or self._kid is None:
            return {"keys": []}
        numbers = self._public_key.public_numbers()
        return {
            "keys": [
                {
                    "kty": "RSA",
                    "use": "sig",
                    "alg": "RS256",
                    "kid": self._kid,
                    "n": _b64url_uint(numbers.n),
                    "e": _b64url_uint(numbers.e),
                }
            ]
        }

    def register_client(
        self,
        *,
        client_name: str,
        redirect_uris: list[str],
        scope: str = "workspace:read collection:read records:read",
    ) -> dict[str, Any]:
        """RFC 7591 Dynamic Client Registration (public PKCE clients)."""
        if not redirect_uris:
            raise ValidationError("At least one redirect_uri is required")
        allow_local = self._settings.app_env != "production"
        validated_uris = [
            validate_redirect_uri(u, allow_localhost_dev=allow_local) for u in redirect_uris
        ]
        allowed_scopes = parse_and_validate_scopes(scope)
        client_id = f"dc_oauth_{secrets.token_hex(12)}"
        doc = {
            "client_id": client_id,
            "client_name": client_name[:120],
            "redirect_uris": validated_uris,
            "allowed_scopes": allowed_scopes,
            "token_endpoint_auth_method": "none",
            "created_at": datetime.now(UTC),
        }
        self._clients.insert_one(doc)
        return {
            "client_id": client_id,
            "client_name": doc["client_name"],
            "redirect_uris": validated_uris,
            "scope": " ".join(allowed_scopes),
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        }

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        return self._clients.find_one({"client_id": client_id})

    def validate_authorize_request(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        raw_scope: str,
        code_challenge: str,
        code_challenge_method: str,
        resource: str | None = None,
    ) -> tuple[dict[str, Any], list[str], str]:
        """Validate authorize request parameters and enforce client scope boundaries."""
        client = self.get_client(client_id)
        if client is None:
            raise BadRequestError("Unknown client_id")
        if redirect_uri not in client.get("redirect_uris", []):
            raise BadRequestError("redirect_uri is not registered for this client")
        if code_challenge_method != "S256" or not code_challenge:
            raise BadRequestError("PKCE code_challenge_method=S256 is required")

        target_resource = resource or self._settings.mcp_public_url
        if target_resource != self._settings.mcp_public_url:
            raise BadRequestError("Requested resource does not match this MCP server")

        requested = parse_and_validate_scopes(raw_scope)
        client_allowed = set(client.get("allowed_scopes") or DEFAULT_CLIENT_SCOPES)
        escalated = [s for s in requested if s not in client_allowed]
        if escalated:
            raise BadRequestError(
                f"Requested scope(s) exceed client registration: {' '.join(escalated)}"
            )
        return client, requested, target_resource

    def create_authorization_code(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        user_id: str,
        email: str,
        scopes: list[str],
        code_challenge: str,
        code_challenge_method: str,
        resource: str | None = None,
    ) -> str:
        """Issue a single-use authorization code bound to client, PKCE, resource, and scopes."""
        _, validated_scopes, target_resource = self.validate_authorize_request(
            client_id=client_id,
            redirect_uri=redirect_uri,
            raw_scope=" ".join(scopes),
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            resource=resource,
        )
        code = secrets.token_urlsafe(32)
        self._codes.insert_one(
            {
                "code_hash": hash_token(code),
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "user_id": user_id,
                "email": email,
                "scopes": validated_scopes,
                "code_challenge": code_challenge,
                "resource": target_resource,
                "used": False,
                "expires_at": datetime.now(UTC) + timedelta(minutes=5),
            }
        )
        return code

    def exchange_code(
        self,
        *,
        code: str,
        client_id: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> dict[str, Any]:
        """Validate client/redirect/PKCE before atomically consuming the authorization code."""
        code_hash = hash_token(code)
        doc = self._codes.find_one({"code_hash": code_hash})
        if doc is None or doc.get("used"):
            raise AuthenticationError("Invalid or already-used authorization code")
        if doc["client_id"] != client_id or doc["redirect_uri"] != redirect_uri:
            raise AuthenticationError("Client or redirect_uri mismatch")
        exp = doc["expires_at"]
        if isinstance(exp, datetime):
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=UTC)
            if exp < datetime.now(UTC):
                raise AuthenticationError("Authorization code expired")
        if not verify_pkce_s256(code_verifier, doc["code_challenge"]):
            raise AuthenticationError("Invalid PKCE code_verifier")

        # Atomic compare-and-consume only after caller proved client + PKCE possession
        consumed = self._codes.find_one_and_update(
            {"_id": doc["_id"], "used": False},
            {"$set": {"used": True}},
        )
        if consumed is None:
            raise AuthenticationError("Authorization code already redeemed")

        return self._mint_oauth_tokens(
            user_id=doc["user_id"],
            email=doc["email"],
            client_id=client_id,
            scopes=doc["scopes"],
            resource=doc["resource"],
            family_id=secrets.token_hex(12),
        )

    def exchange_refresh_token(
        self,
        *,
        refresh_token: str,
        client_id: str,
        raw_scope: str | None = None,
    ) -> dict[str, Any]:
        """Atomically rotate OAuth refresh token with replay revocation and scope checks."""
        tok_hash = hash_token(refresh_token)
        rec = self._refresh_tokens.find_one_and_update(
            {"token_hash": tok_hash, "revoked_at": None},
            {"$set": {"revoked_at": datetime.now(UTC)}},
        )
        if rec is None:
            existing = self._refresh_tokens.find_one({"token_hash": tok_hash})
            if existing is not None and existing.get("revoked_at") is not None:
                self._refresh_tokens.update_many(
                    {"family_id": existing["family_id"]},
                    {"$set": {"revoked_at": datetime.now(UTC)}},
                )
                raise AuthenticationError("Refresh token reused; OAuth session revoked")
            raise AuthenticationError("Invalid refresh token")

        if rec["client_id"] != client_id:
            raise AuthenticationError("Refresh token does not belong to client_id")

        exp = rec["expires_at"]
        if isinstance(exp, datetime):
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=UTC)
            if exp < datetime.now(UTC):
                raise AuthenticationError("Refresh token expired")

        user = self._db.users.find_one({"_id": rec["user_id"]})
        if user is not None and user.get("status") != "active":
            raise AuthenticationError("User account is disabled")

        granted_scopes: list[str] = list(rec["scopes"])
        if raw_scope:
            requested = parse_and_validate_scopes(raw_scope)
            if not set(requested).issubset(set(granted_scopes)):
                raise BadRequestError("Requested refresh scope exceeds original grant")
            granted_scopes = requested

        return self._mint_oauth_tokens(
            user_id=rec["user_id"],
            email=rec["email"],
            client_id=client_id,
            scopes=granted_scopes,
            resource=rec["resource"],
            family_id=rec["family_id"],
        )

    def _mint_oauth_tokens(
        self,
        *,
        user_id: str,
        email: str,
        client_id: str,
        scopes: list[str],
        resource: str,
        family_id: str,
    ) -> dict[str, Any]:
        if self._private_key is None or self._kid is None:
            raise AuthenticationError("Local OAuth signing key is not available")
        now = datetime.now(UTC)
        jti = secrets.token_hex(12)
        issuer = self._settings.auth_issuer.rstrip("/")
        payload = {
            "sub": user_id,
            "email": email,
            "client_id": client_id,
            "iss": issuer,
            "aud": resource,
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int(
                (now + timedelta(seconds=self._settings.access_token_ttl_seconds)).timestamp()
            ),
            "jti": jti,
            "scope": " ".join(scopes),
            "scopes": scopes,
        }
        access_token = jwt.encode(
            payload,
            self._private_key,
            algorithm="RS256",
            headers={"kid": self._kid},
        )
        raw_refresh = secrets.token_urlsafe(48)
        self._refresh_tokens.insert_one(
            {
                "token_hash": hash_token(raw_refresh),
                "family_id": family_id,
                "client_id": client_id,
                "user_id": user_id,
                "email": email,
                "scopes": scopes,
                "resource": resource,
                "revoked_at": None,
                "expires_at": now + timedelta(seconds=self._settings.refresh_token_ttl_seconds),
                "created_at": now,
            }
        )
        return {
            "access_token": access_token,
            "refresh_token": raw_refresh,
            "token_type": "Bearer",
            "expires_in": self._settings.access_token_ttl_seconds,
            "scope": " ".join(scopes),
        }

    def revoke_token(self, token: str, *, client_id: str) -> None:
        """RFC 7009 revocation bound to verified signature or hashed refresh token + client_id."""
        if not client_id:
            raise BadRequestError("client_id is required for revocation")

        # 1. Try revoking as OAuth refresh token owned by client_id
        tok_hash = hash_token(token)
        rt = self._refresh_tokens.find_one({"token_hash": tok_hash, "client_id": client_id})
        if rt is not None:
            self._refresh_tokens.update_many(
                {"family_id": rt["family_id"]},
                {"$set": {"revoked_at": datetime.now(UTC)}},
            )
            return

        # 2. Otherwise verify access token signature cryptographically before trusting jti
        if self._public_key is None:
            return
        try:
            payload = jwt.decode(
                token,
                self._public_key,
                algorithms=["RS256"],
                issuer=self._settings.auth_issuer.rstrip("/"),
                audience=self._settings.mcp_public_url,
            )
        except jwt.PyJWTError:
            return  # RFC 7009: invalid/unknown token returns 200 without leaking state

        if not hmac.compare_digest(str(payload.get("client_id", "")), client_id):
            return
        jti = payload.get("jti")
        if isinstance(jti, str) and jti:
            self._revoked.update_one(
                {"jti": jti},
                {"$set": {"revoked_at": datetime.now(UTC)}},
                upsert=True,
            )

    def verify_bearer_token(self, token: str, *, is_mcp: bool = True) -> Actor:
        """Verify RS256/ES256 OAuth access token bound strictly to MCP_PUBLIC_URL."""
        issuer = self._settings.auth_issuer.rstrip("/")
        audience = self._settings.mcp_public_url
        try:
            if self._settings.oauth_mode == "external":
                if self._jwk_client is None:
                    raise AuthenticationError("External JWKS URL is not configured")
                signing_key = self._jwk_client.get_signing_key_from_jwt(token)
                payload = jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=["RS256", "ES256"],
                    issuer=issuer,
                    audience=audience,
                )
            else:
                if self._public_key is None:
                    raise AuthenticationError("Builtin OAuth public key is not available")
                payload = jwt.decode(
                    token,
                    self._public_key,
                    algorithms=["RS256"],
                    issuer=issuer,
                    audience=audience,
                )
        except jwt.PyJWTError as exc:
            raise AuthenticationError("Invalid, expired, or wrong-audience OAuth token") from exc

        jti = payload.get("jti")
        if isinstance(jti, str) and self._revoked.find_one({"jti": jti}) is not None:
            raise AuthenticationError("OAuth token has been revoked")

        sub = payload.get("sub")
        if not isinstance(sub, str) or not sub:
            raise AuthenticationError("OAuth token missing subject")

        raw_scopes = payload.get("scopes")
        if not isinstance(raw_scopes, list):
            scope_str = str(payload.get("scope", ""))
            raw_scopes = [s for s in scope_str.split() if s]

        parsed_scopes: set[Scope] = set()
        for s in raw_scopes:
            with contextlib.suppress(ValueError):
                parsed_scopes.add(Scope(s))

        return Actor(
            principal_id=sub,
            principal_type=PrincipalType.OAUTH_CLIENT,
            email=payload.get("email"),
            scopes=frozenset(parsed_scopes),
            client_id=payload.get("client_id"),
            is_mcp=is_mcp,
            mcp_allow_writes=self._settings.mcp_allow_writes,
        )
