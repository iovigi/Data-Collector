"""Durable artifact storage abstraction for imports and exports."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

from data_collector.domain.exceptions import NotFoundError, ValidationError


class ArtifactStore(Protocol):
    """Protocol for durable, tenant-scoped import/export artifact storage."""

    def put_bytes(self, key: str, data: bytes) -> tuple[str, int]:
        """Store bytes under opaque key; returns (sha256, byte_length)."""
        ...

    def open_write_stream(self, key: str) -> Path:
        """Return a safe local staging path for streaming writes."""
        ...

    def finalize_stream(self, path: Path) -> tuple[str, int]:
        """Compute (sha256, byte_length) for a streamed artifact."""
        ...

    def get_path(self, key: str) -> Path:
        """Resolve readable local path for an artifact key."""
        ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...


class LocalVolumeArtifactStore:
    """Shared volume-backed ArtifactStore with strict path-traversal defense."""

    def __init__(self, root_dir: str) -> None:
        self._root = Path(root_dir).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, key: str) -> Path:
        if not key or ".." in key or key.startswith(("/", "\\")):
            raise ValidationError("Invalid artifact key")
        target = (self._root / key).resolve()
        if self._root not in target.parents and target != self._root:
            raise ValidationError("Artifact key escapes storage root")
        return target

    def put_bytes(self, key: str, data: bytes) -> tuple[str, int]:
        target = self._safe_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return hashlib.sha256(data).hexdigest(), len(data)

    def open_write_stream(self, key: str) -> Path:
        target = self._safe_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def finalize_stream(self, path: Path) -> tuple[str, int]:
        h = hashlib.sha256()
        size = 0
        with path.open("rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
                size += len(chunk)
        return h.hexdigest(), size

    def get_path(self, key: str) -> Path:
        target = self._safe_path(key)
        if not target.exists():
            raise NotFoundError("Artifact not found")
        return target

    def exists(self, key: str) -> bool:
        return self._safe_path(key).exists()

    def delete(self, key: str) -> None:
        target = self._safe_path(key)
        if target.exists():
            target.unlink()

    def iter_chunks(self, key: str, chunk_size: int = 65536) -> Iterator[bytes]:
        path = self.get_path(key)
        with path.open("rb") as f:
            while chunk := f.read(chunk_size):
                yield chunk
