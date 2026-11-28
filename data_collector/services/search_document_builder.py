"""Safe, bounded extraction of nested MongoDB documents into external search docs.

Never modifies source records. Enforces depth, field count, array length,
single-string byte size, and total document byte size limits, and skips
binary/secret-like fields.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from bson import ObjectId

_DEFAULT_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passphrase",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "private_key",
        "client_secret",
        "ssn",
    }
)
_BASE64_BLOB_RE = re.compile(r"^[A-Za-z0-9+/=_-]{256,}$")
_WHITESPACE_RE = re.compile(r"\s+")


def _escape_segment(seg: str) -> str:
    return seg.replace("\\", "\\\\").replace(".", "\\.")


def _normalize_text(val: str) -> str:
    normalized = unicodedata.normalize("NFKC", val)
    return _WHITESPACE_RE.sub(" ", normalized).strip()


@dataclass(frozen=True)
class ExtractedSearchDoc:
    """Ephemeral derived search document stored only in the external search engine."""

    search_doc_id: str
    workspace_id: str
    project_id: str
    collection_id: str
    source_id: str
    indexed_source_version: int
    source_updated_at: str | None
    active: bool
    text_fields: dict[str, str]
    path_tokens: list[str]
    display_snippet: str
    extraction_truncated: bool

    def to_index_payload(self) -> dict[str, Any]:
        return {
            "search_doc_id": self.search_doc_id,
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "collection_id": self.collection_id,
            "source_id": self.source_id,
            "indexed_source_version": self.indexed_source_version,
            "source_updated_at": self.source_updated_at,
            "active": self.active,
            "text_fields": self.text_fields,
            "path_tokens": self.path_tokens,
            "display_snippet": self.display_snippet,
            "extraction_truncated": self.extraction_truncated,
        }


def build_search_document(
    record: dict[str, Any],
    *,
    excluded_fields: set[str] | None = None,
    allowed_fields: set[str] | None = None,
    max_depth: int = 8,
    max_fields: int = 200,
    max_array_items: int = 100,
    max_string_bytes: int = 4096,
    max_total_bytes: int = 32768,
) -> ExtractedSearchDoc:
    """Deterministically flatten `record['data']` into path-tagged text fields."""
    ws_id = str(record["workspace_id"])
    proj_id = str(record["project_id"])
    col_id = str(record["collection_id"])
    source_id = str(record.get("id") or record.get("_id"))
    search_doc_id = f"{ws_id}_{col_id}_{source_id}"

    updated_raw = record.get("updated_at")
    if isinstance(updated_raw, datetime):
        updated_iso: str | None = updated_raw.isoformat()
    elif updated_raw is not None:
        updated_iso = str(updated_raw)
    else:
        updated_iso = None

    excluded = {k.lower() for k in (excluded_fields or set())} | _DEFAULT_SENSITIVE_KEYS
    text_fields: dict[str, list[str]] = {}
    path_tokens: list[str] = []
    seen_paths: set[str] = set()
    state = {"fields": 0, "bytes": 0, "truncated": False}

    def _add_value(path: str, raw_val: str) -> None:
        if state["fields"] >= max_fields or state["bytes"] >= max_total_bytes:
            state["truncated"] = True
            return
        cleaned = _normalize_text(raw_val)
        if not cleaned:
            return
        encoded = cleaned.encode("utf-8")
        if len(encoded) > max_string_bytes:
            cleaned = encoded[:max_string_bytes].decode("utf-8", errors="ignore")
            state["truncated"] = True
        remaining = max_total_bytes - state["bytes"]
        if len(cleaned.encode("utf-8")) > remaining:
            cleaned = cleaned.encode("utf-8")[:remaining].decode("utf-8", errors="ignore")
            state["truncated"] = True
        if not cleaned:
            return
        if path not in text_fields:
            state["fields"] += 1
            text_fields[path] = []
        if path not in seen_paths:
            seen_paths.add(path)
            path_tokens.append(path)
        text_fields[path].append(cleaned)
        state["bytes"] += len(cleaned.encode("utf-8"))

    def _walk(node: Any, path: str, depth: int, in_array: bool = False) -> None:
        if state["truncated"] and state["bytes"] >= max_total_bytes:
            return
        if depth > max_depth:
            state["truncated"] = True
            return
        if node is None:
            return
        if isinstance(node, (bytes, bytearray, memoryview)):
            state["truncated"] = True
            return
        if isinstance(node, bool):
            _add_value(path, "true" if node else "false")
            return
        if isinstance(node, (int, float)):
            _add_value(path, str(node))
            return
        if isinstance(node, ObjectId):
            _add_value(path, str(node))
            return
        if isinstance(node, datetime):
            _add_value(path, node.isoformat())
            return
        if isinstance(node, str):
            if _BASE64_BLOB_RE.match(node.strip()):
                state["truncated"] = True
                return
            _add_value(path, node)
            return
        if isinstance(node, list):
            arr_path = f"{path}[]" if path and not path.endswith("[]") else (path or "[]")
            for idx, item in enumerate(node):
                if idx >= max_array_items:
                    state["truncated"] = True
                    break
                _walk(item, arr_path, depth + 1, in_array=True)
            return
        if isinstance(node, dict):
            for raw_key, val in node.items():
                key_str = str(raw_key)
                if key_str.lower() in excluded:
                    continue
                escaped = _escape_segment(key_str)
                child_path = f"{path}.{escaped}" if path else escaped
                if (
                    depth == 1
                    and allowed_fields is not None
                    and key_str not in allowed_fields
                ):
                    continue
                if child_path.lower() in excluded:
                    continue
                _walk(val, child_path, depth + 1, in_array=in_array)

    data_obj = record.get("data")
    if isinstance(data_obj, dict):
        _walk(data_obj, "", 1)

    joined_fields = {k: " | ".join(v) for k, v in text_fields.items() if v}
    snippet_parts: list[str] = []
    for k, v in joined_fields.items():
        snippet_parts.append(f"{k}: {v}")
        if sum(len(p) for p in snippet_parts) >= 240:
            break
    snippet = " · ".join(snippet_parts)[:240]

    return ExtractedSearchDoc(
        search_doc_id=search_doc_id,
        workspace_id=ws_id,
        project_id=proj_id,
        collection_id=col_id,
        source_id=source_id,
        indexed_source_version=int(record.get("version") or 1),
        source_updated_at=updated_iso,
        active=record.get("deleted_at") is None,
        text_fields=joined_fields,
        path_tokens=path_tokens,
        display_snippet=snippet,
        extraction_truncated=bool(state["truncated"]),
    )
