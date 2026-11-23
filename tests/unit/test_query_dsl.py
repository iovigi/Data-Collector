"""Unit and security tests for Safe Query DSL compiler and cursor codec."""

from __future__ import annotations

import pytest
from data_collector.domain.exceptions import ValidationError
from data_collector.services.query_dsl import (
    compile_filter,
    compile_projection,
    decode_cursor,
    encode_cursor,
    query_signature,
)


def test_compile_valid_and_or_filter():
    ast = {
        "and": [
            {"field": "status", "op": "eq", "value": "active"},
            {"field": "score", "op": "gte", "value": 10},
        ]
    }
    compiled = compile_filter(ast, allowed_fields={"status", "score"})
    assert compiled == {
        "$and": [
            {"data.status": "active"},
            {"data.score": {"$gte": 10}},
        ]
    }


@pytest.mark.parametrize(
    "bad_ast",
    [
        {"$where": "this.a > 1"},
        {"$expr": {"$gt": ["$a", 1]}},
        {"field": "status", "op": "regex", "value": ".*"},
        {"field": "$where", "op": "eq", "value": "1"},
        {"field": "__proto__.polluted", "op": "eq", "value": 1},
        {"field": "status", "op": "eq", "value": {"$ne": None}},
        {"field": "secret_field", "op": "eq", "value": "x"},
    ],
)
def test_reject_injection_and_disallowed_fields(bad_ast):
    with pytest.raises(ValidationError):
        compile_filter(bad_ast, allowed_fields={"status", "score"})


def test_reject_excessive_depth_and_branches():
    deep = {"not": {"not": {"not": {"not": {"field": "status", "op": "eq", "value": "a"}}}}}
    with pytest.raises(ValidationError, match="depth"):
        compile_filter(deep, allowed_fields={"status"})

    too_many = {"and": [{"field": "status", "op": "eq", "value": str(i)} for i in range(21)]}
    with pytest.raises(ValidationError, match="20"):
        compile_filter(too_many, allowed_fields={"status"})


def test_projection_and_cursor_binding():
    proj = compile_projection(["status"], allowed_fields={"status", "score"})
    assert proj is not None
    assert proj["data.status"] == 1
    assert "data.score" not in proj

    secret = "cursor-secret-key-32-chars-minimum"
    sig = query_signature(
        "ws1", "col1", {"field": "status", "op": "eq", "value": "ok"}, "created_at", "desc"
    )
    cur = encode_cursor(
        secret=secret,
        sig=sig,
        sort_value="2026-01-01T00:00:00Z",
        last_id="507f1f77bcf86cd799439011",
    )

    decoded = decode_cursor(
        cursor=cur,
        secret=secret,
        expected_sig=sig,
        sort_field="created_at",
        sort_direction=-1,
    )
    assert "$or" in decoded

    other_sig = query_signature(
        "ws2", "col1", {"field": "status", "op": "eq", "value": "ok"}, "created_at", "desc"
    )
    with pytest.raises(ValidationError, match="does not match"):
        decode_cursor(
            cursor=cur,
            secret=secret,
            expected_sig=other_sig,
            sort_field="created_at",
            sort_direction=-1,
        )
