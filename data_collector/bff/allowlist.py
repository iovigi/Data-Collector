"""Exact allowlist of REST v1 paths reachable through the browser BFF (`/api/backend/*`).

Ported 1:1 from the former Next.js ``lib/api/allowlist.ts``. Only these API paths can be
reached with a browser session; everything else is rejected before any dispatch.
"""

from __future__ import annotations

import re

_ID = r"[a-f0-9]{24}"

_PATTERNS = [
    r"me",
    r"openapi\.json",
    r"workspaces",
    rf"workspaces/{_ID}",
    rf"workspaces/{_ID}/(archive|restore|capabilities|dashboard/summary|members|invitations"
    r"|transfer-ownership|projects|jobs|audit|webhooks|usage)",
    rf"workspaces/{_ID}/members/{_ID}",
    rf"workspaces/{_ID}/webhooks/{_ID}",
    rf"workspaces/{_ID}/webhooks/{_ID}/(rotate-secret|deliveries)",
    rf"invitations/{_ID}/(accept|revoke)",
    rf"projects/{_ID}",
    rf"projects/{_ID}/(archive|restore|collections)",
    rf"collections/{_ID}",
    rf"collections/{_ID}/(records|records/batch|records/search|records/trash|imports|exports"
    r"|saved-queries|schema-migrations/preview|schema-migrations/apply)",
    rf"collections/{_ID}/records/{_ID}",
    rf"collections/{_ID}/records/{_ID}/restore",
    rf"saved-queries/{_ID}",
    rf"saved-queries/{_ID}/run",
    rf"jobs/{_ID}",
    rf"jobs/{_ID}/(result|cancel)",
    r"keys",
    rf"keys/{_ID}/revoke",
    r"audit",
]

_COMPILED = [re.compile(p) for p in _PATTERNS]


def is_allowed_backend_path(joined: str) -> bool:
    if (
        not joined
        or ".." in joined
        or "://" in joined
        or joined.startswith("/")
        or "\\" in joined
        or "%" in joined
    ):
        return False
    return any(rx.fullmatch(joined) for rx in _COMPILED)
