"""Application configuration with fail-fast production validation."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_WEAK_SECRETS = frozenset(
    {
        "",
        "your-secret-key",
        "secret",
        "changeme",
        "dev-secret",
        "admin",
        "password",
    }
)


class Settings(BaseSettings):
    """Typed application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["development", "test", "production"] = Field(default="development")
    app_host: str = Field(default="127.0.0.1")
    app_port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = Field(default="INFO")

    # Database & Cache
    mongodb_uri: str = Field(default="mongodb://localhost:27017/")
    mongodb_db: str = Field(default="data_collector")
    mongodb_max_pool_size: int = Field(default=50, ge=1, le=500)
    mongodb_server_selection_timeout_ms: int = Field(default=5000, ge=500)
    redis_url: str = Field(default="redis://localhost:6379/0")

    # Security & Auth
    jwt_secret_key: str = Field(default="")
    intent_secret_key: str = Field(default="")
    auth_issuer: str = Field(default="https://auth.example.com/")
    auth_audience: str = Field(default="data-collector-api")
    access_token_ttl_seconds: int = Field(default=900, ge=60, le=86400)
    refresh_token_ttl_seconds: int = Field(default=604800, ge=300, le=2592000)

    # CORS
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Legacy compatibility flags (fail-closed by default)
    enable_legacy_api: bool = Field(default=False)
    enable_legacy_system_auth: bool = Field(default=False)
    legacy_system_auth_key: str = Field(default="")

    # Rate limits & Quotas
    rate_limit_read_per_minute: int = Field(default=60, ge=1)
    rate_limit_write_per_minute: int = Field(default=30, ge=1)
    rate_limit_login_per_minute: int = Field(default=10, ge=1)
    rate_limit_workspace_per_minute: int = Field(default=600, ge=1)
    rate_limit_fail_closed_mutations: bool = Field(default=True)

    # Payload & Query limits
    max_json_body_bytes: int = Field(default=1_048_576, ge=1024)
    max_batch_records: int = Field(default=500, ge=1, le=5000)
    max_batch_bytes: int = Field(default=5_242_880, ge=1024)
    max_import_bytes: int = Field(default=52_428_800, ge=1024)
    max_query_page_size: int = Field(default=100, ge=1, le=500)
    default_query_page_size: int = Field(default=25, ge=1, le=100)
    max_query_time_ms: int = Field(default=5000, ge=100, le=30000)
    # Server-side aggregations (dc_aggregate, analytics REST): per-query time budget.
    analytics_max_time_ms: int = Field(default=15000, ge=100, le=60000)
    soft_delete_retention_days: int = Field(default=30, ge=1)

    # Storage & Exports
    storage_dir: str = Field(default="./var/storage")
    export_sync_max_records: int = Field(default=1000, ge=1)

    # MCP & OAuth
    oauth_mode: Literal["builtin", "external"] = Field(default="builtin")
    oauth_jwks_url: str = Field(default="")
    oauth_rsa_private_key_pem: str = Field(default="")
    mcp_public_url: str = Field(default="http://127.0.0.1:8001/mcp")
    mcp_host: str = Field(default="127.0.0.1")
    mcp_port: int = Field(default=8001, ge=1, le=65535)
    mcp_max_output_bytes: int = Field(default=262_144, ge=4096)
    mcp_allow_writes: bool = Field(default=False)

    # Metrics
    metrics_auth_token: str = Field(default="")

    # Async jobs: when true the API enqueues import/export jobs to Redis (RQ) for the
    # independent worker process instead of executing them inside the web request.
    jobs_async: bool = Field(default=False)

    # Python BFF for the Admin UI (IIS-native single-origin hosting)
    web_session_secret: str = Field(default="")
    web_session_ttl_seconds: int = Field(default=604800, ge=300, le=2592000)
    web_dist_dir: str = Field(default="")
    # Trust CF-Connecting-IP only when the TCP peer is inside Cloudflare's published ranges.
    trust_cloudflare_client_ip: bool = Field(default=False)
    log_dir: str = Field(default="")
    # Serve /mcp + OAuth inside the same WSGI process (stateless JSON Streamable HTTP).
    mcp_http_in_process: bool = Field(default=False)

    # Tiered Collection Counts (million-record safe)
    collection_counts_enabled: bool = Field(default=True)
    collection_count_cache_ttl_seconds: int = Field(default=900, ge=10, le=86400)
    collection_count_max_time_ms: int = Field(default=1000, ge=100, le=30000)
    collection_count_max_concurrent: int = Field(default=1, ge=1, le=16)
    collection_count_batch_max: int = Field(default=25, ge=1, le=100)
    collection_count_background_refresh: bool = Field(default=False)

    # Structured Search Planner
    structured_search_max_time_ms: int = Field(default=1500, ge=100, le=30000)
    structured_search_max_page_size: int = Field(default=100, ge=1, le=500)
    structured_search_allow_unindexed: bool = Field(default=False)
    structured_search_block_broad_contains: bool = Field(default=True)

    # External Full-Text Search & Isolated Backfill Indexer (disabled by default)
    fulltext_search_enabled: bool = Field(default=False)
    fulltext_search_backend: Literal["disabled", "memory", "meilisearch", "opensearch"] = Field(
        default="disabled"
    )
    fulltext_search_url: str = Field(default="")
    fulltext_search_api_key: str = Field(default="")
    fulltext_search_timeout_ms: int = Field(default=2000, ge=100, le=30000)
    fulltext_search_max_concurrent: int = Field(default=4, ge=1, le=64)
    fulltext_search_max_query_length: int = Field(default=256, ge=16, le=1024)
    fulltext_search_batch_hydrate_max: int = Field(default=50, ge=1, le=200)
    search_source_mongodb_uri: str = Field(default="")
    search_auxiliary_mongodb_uri: str = Field(default="")
    search_auxiliary_mongodb_db: str = Field(default="data_collector_search_aux")
    search_backfill_enabled: bool = Field(default=False)
    search_backfill_batch_size: int = Field(default=100, ge=1, le=1000)
    search_backfill_max_docs_per_second: int = Field(default=50, ge=1, le=10000)
    search_backfill_max_bytes_per_second: int = Field(default=1_048_576, ge=1024)
    search_backfill_max_concurrent_collections: int = Field(default=1, ge=1, le=8)
    search_backfill_pause_on_high_db_latency: bool = Field(default=True)
    search_backfill_max_db_latency_ms: int = Field(default=250, ge=10, le=10000)
    search_external_auxiliary_namespace: str = Field(default="dc_search_v1")

    @field_validator("app_env", mode="before")
    @classmethod
    def _normalize_env(cls, v: object) -> str:
        val = str(v or "development").strip().lower()
        mapping = {
            "dev": "development",
            "development": "development",
            "test": "test",
            "testing": "test",
            "prod": "production",
            "production": "production",
        }
        if val not in mapping:
            raise ValueError(f"Invalid APP_ENV '{v}'; expected dev|test|prod")
        return mapping[val]

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _parse_origins(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        if isinstance(v, list):
            return [str(item).strip() for item in v if str(item).strip()]
        return []

    @model_validator(mode="after")
    def _validate_security(self) -> Settings:
        secret = self.jwt_secret_key.strip()
        if self.app_env == "production":
            if secret in _WEAK_SECRETS or len(secret) < 32:
                raise ValueError(
                    "JWT_SECRET_KEY must be at least 32 characters and non-default in production"
                )
            if not self.allowed_origins or "*" in self.allowed_origins:
                raise ValueError(
                    "ALLOWED_ORIGINS must be explicitly configured without '*' in production"
                )
            if not self.mongodb_uri:
                raise ValueError("MONGODB_URI is required in production")
            if self.enable_legacy_system_auth:
                raise ValueError("ENABLE_LEGACY_SYSTEM_AUTH is prohibited in production")
            if not self.mcp_public_url.startswith("https://"):
                raise ValueError("MCP_PUBLIC_URL must use https:// in production")
            if not self.auth_issuer.startswith("https://"):
                raise ValueError("AUTH_ISSUER must use https:// in production")
            if self.oauth_mode == "builtin" and not self.oauth_rsa_private_key_pem.strip():
                raise ValueError(
                    "OAUTH_RSA_PRIVATE_KEY_PEM is required in production when OAUTH_MODE=builtin"
                )
            if self.oauth_mode == "external" and not self.oauth_jwks_url.startswith("https://"):
                raise ValueError(
                    "OAUTH_JWKS_URL (https://) is required in production when OAUTH_MODE=external"
                )
            web_secret = self.web_session_secret.strip()
            if web_secret and (
                web_secret in _WEAK_SECRETS or len(web_secret) < 32 or web_secret == secret
            ):
                raise ValueError(
                    "WEB_SESSION_SECRET must be >= 32 characters, non-default and distinct "
                    "from JWT_SECRET_KEY in production"
                )
        else:
            if not secret:
                # Ephemeral per-process random fallback only for dev/test when unset;
                # never a static hardcoded string.
                object.__setattr__(self, "jwt_secret_key", os.urandom(32).hex())
            elif secret in _WEAK_SECRETS:
                raise ValueError("JWT_SECRET_KEY cannot be set to a known weak/default value")

        if self.oauth_rsa_private_key_pem.strip():
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import rsa

            try:
                pem_bytes = self.oauth_rsa_private_key_pem.replace("\\n", "\n").encode("utf-8")
                key = serialization.load_pem_private_key(pem_bytes, password=None)
            except Exception as exc:
                raise ValueError(
                    "OAUTH_RSA_PRIVATE_KEY_PEM could not be parsed as a valid PEM private key"
                ) from exc
            if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
                raise ValueError(
                    "OAUTH_RSA_PRIVATE_KEY_PEM must be an RSA key of at least 2048 bits"
                )

        if not self.intent_secret_key.strip():
            object.__setattr__(self, "intent_secret_key", self.jwt_secret_key)

        if not self.web_session_secret.strip() and self.app_env != "production":
            # dev/test only: ephemeral per-process secret (production must configure one)
            object.__setattr__(self, "web_session_secret", os.urandom(32).hex())

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()


def reset_settings_cache() -> None:
    """Clear settings cache (used in tests)."""
    get_settings.cache_clear()
