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
    soft_delete_retention_days: int = Field(default=30, ge=1)

    # Storage & Exports
    storage_dir: str = Field(default="./var/storage")
    export_sync_max_records: int = Field(default=1000, ge=1)

    # MCP & OAuth
    mcp_public_url: str = Field(default="http://127.0.0.1:8001/mcp")
    mcp_host: str = Field(default="127.0.0.1")
    mcp_port: int = Field(default=8001, ge=1, le=65535)
    mcp_max_output_bytes: int = Field(default=262_144, ge=4096)
    mcp_allow_writes: bool = Field(default=False)

    # Metrics
    metrics_auth_token: str = Field(default="")

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
        else:
            if not secret:
                # Ephemeral per-process random fallback only for dev/test when unset;
                # never a static hardcoded string.
                object.__setattr__(self, "jwt_secret_key", os.urandom(32).hex())
            elif secret in _WEAK_SECRETS:
                raise ValueError("JWT_SECRET_KEY cannot be set to a known weak/default value")

        if not self.intent_secret_key.strip():
            object.__setattr__(self, "intent_secret_key", self.jwt_secret_key)

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()


def reset_settings_cache() -> None:
    """Clear settings cache (used in tests)."""
    get_settings.cache_clear()
