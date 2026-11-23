"""Unit tests for Settings validation and cryptographic helpers."""

from __future__ import annotations

import bcrypt
import pytest
from data_collector.config import Settings
from data_collector.infrastructure.crypto import (
    generate_api_key,
    hash_password,
    sign_intent_token,
    verify_intent_token,
    verify_password,
    verify_token_hash,
)
from pydantic import ValidationError


def test_prod_rejects_missing_or_weak_secret():
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            jwt_secret_key="short",
            allowed_origins=["https://app.example.com"],
        )

    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            jwt_secret_key="your-secret-key",
            allowed_origins=["https://app.example.com"],
        )


def test_prod_rejects_wildcard_cors_and_legacy_system_auth():
    strong = "x" * 40
    with pytest.raises(ValidationError):
        Settings(app_env="production", jwt_secret_key=strong, allowed_origins=["*"])

    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            jwt_secret_key=strong,
            allowed_origins=["https://app.example.com"],
            enable_legacy_system_auth=True,
        )


def test_argon2_hash_and_bcrypt_migration():
    h = hash_password("SuperSecurePassword123!")
    assert h.startswith("$argon2")
    ok, rehash = verify_password("SuperSecurePassword123!", h)
    assert ok is True
    assert rehash is False

    bad, _ = verify_password("wrong", h)
    assert bad is False

    # Legacy bcrypt should verify and flag needs_rehash=True
    b_hash = bcrypt.hashpw(b"LegacyPass1234", bcrypt.gensalt()).decode("utf-8")
    ok_b, rehash_b = verify_password("LegacyPass1234", b_hash)
    assert ok_b is True
    assert rehash_b is True


def test_api_key_generation_and_verification():
    plaintext, prefix, key_hash = generate_api_key()
    assert plaintext.startswith(f"{prefix}.")
    assert verify_token_hash(plaintext, key_hash) is True
    assert verify_token_hash("wrong", key_hash) is False


def test_intent_token_sign_verify_and_expiry():
    secret = "intent-secret-32-chars-minimum-12345"
    tok = sign_intent_token({"action": "delete", "rid": "123"}, secret, ttl_seconds=60)
    decoded = verify_intent_token(tok, secret)
    assert decoded is not None
    assert decoded["rid"] == "123"
    assert verify_intent_token(tok, "wrong-secret") is None

    expired = sign_intent_token({"action": "delete"}, secret, ttl_seconds=-1)
    assert verify_intent_token(expired, secret) is None
