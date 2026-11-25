"""HTML for the OAuth sign-in and consent screens (server-rendered, no external assets).

Every interpolated value is HTML-escaped. Pages are sent with anti-framing headers.
No `form-action` CSP: browsers apply it to the post-submit redirect, which must reach the
client's redirect_uri (claude.ai, chatgpt.com, or a loopback listener).
"""

from __future__ import annotations

import html
from typing import Any

from data_collector.infrastructure.oauth import WRITE_OAUTH_SCOPES

SCOPE_WORDS: dict[str, str] = {
    "workspace:read": "See the workspace and its projects",
    "collection:read": "See collections, their fields and schemas",
    "records:read": "Read records and run counts, breakdowns and charts",
    "records:write": "Create and change records",
    "records:delete": "Delete records (each delete needs a separate confirmation step)",
    "jobs:read": "See import and export jobs",
    "jobs:create": "Start imports and exports",
    "export:read": "Export data",
}

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"
    ),
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}

_CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#f4f5f7;
color:#1c1e21;margin:0;padding:32px 16px}
.card{max-width:460px;margin:0 auto;background:#fff;border:1px solid #dcdfe4;border-radius:12px;
padding:28px;box-shadow:0 2px 10px rgba(0,0,0,.05)}
h1{font-size:20px;margin:0 0 4px}.muted{color:#5f6368;font-size:13px}
.app{font-size:15px;margin:16px 0}.app strong{font-size:16px}
ul{padding-left:20px;margin:8px 0 16px}li{margin:4px 0;font-size:14px}
.badge{display:inline-block;border-radius:999px;padding:2px 10px;font-size:12px;font-weight:600}
.ro{background:#e6f4ea;color:#137333}.rw{background:#fef7e0;color:#b06000}
label{display:block;font-size:13px;font-weight:600;margin:12px 0 4px}
input[type=email],input[type=password],select{width:100%;box-sizing:border-box;padding:9px 10px;
border:1px solid #c4c7cc;border-radius:8px;font-size:14px}
.check{display:flex;gap:8px;align-items:flex-start;font-weight:400;margin-top:12px}
.row{display:flex;gap:8px;margin-top:20px}
button{flex:1;padding:10px;border-radius:8px;border:1px solid #c4c7cc;background:#fff;
font-size:14px;cursor:pointer}button.primary{background:#1a73e8;border-color:#1a73e8;color:#fff}
.err{background:#fce8e6;color:#a50e0e;border-radius:8px;padding:8px 10px;font-size:13px}
code{font-size:12px;background:#f1f3f4;padding:1px 4px;border-radius:4px}
"""


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{_e(title)}</title><style>{_CSS}</style></head>"
        f"<body><div class='card'>{body}</div></body></html>"
    )


def _hidden(fields: dict[str, str]) -> str:
    return "".join(
        f"<input type='hidden' name='{_e(k)}' value='{_e(v)}'/>" for k, v in fields.items()
    )


def _scope_list(scopes: list[str]) -> str:
    return "".join(f"<li>{_e(SCOPE_WORDS.get(s, s))}</li>" for s in scopes)


def access_level(scopes: list[str], writes_enabled: bool) -> tuple[bool, str]:
    """(is_write, explanation) for the scopes actually effective on this server."""
    wants_write = any(s in WRITE_OAUTH_SCOPES for s in scopes)
    if wants_write and writes_enabled:
        return True, "Can change data (only if you allow it below)"
    if wants_write:
        return False, "Read-only: this server does not accept changes from AI clients"
    return False, "Read-only"


def render_signin(
    *,
    client_name: str,
    redirect_host: str,
    scopes: list[str],
    writes_enabled: bool,
    hidden: dict[str, str],
    csrf_token: str,
    error: str | None = None,
) -> str:
    is_write, level = access_level(scopes, writes_enabled)
    badge = f"<span class='badge {'rw' if is_write else 'ro'}'>{_e(level)}</span>"
    err = f"<p class='err'>{_e(error)}</p>" if error else ""
    body = (
        "<h1>Authorize MCP Client</h1>"
        "<p class='muted'>Sign in to Data Collector to review and approve access.</p>"
        f"<p class='app'><strong>{_e(client_name)}</strong><br/>"
        f"<span class='muted'>will return to <code>{_e(redirect_host)}</code></span></p>"
        f"<p>It asks to:</p><ul>{_scope_list(scopes)}</ul><p>{badge}</p>{err}"
        "<form method='post' action='/oauth/authorize'>"
        f"{_hidden({**hidden, 'csrf_token': csrf_token, 'step': 'login'})}"
        "<label for='email'>Email</label>"
        "<input id='email' name='email' type='email' autocomplete='username' required/>"
        "<label for='password'>Password</label>"
        "<input id='password' name='password' type='password' autocomplete='current-password'"
        " required/>"
        "<div class='row'><button type='submit' name='consent' value='deny' formnovalidate>"
        "Deny</button>"
        "<button class='primary' type='submit' name='consent' value='continue'>"
        "Continue</button></div></form>"
    )
    return _page("Authorize MCP Client", body)


def render_consent(
    *,
    client_name: str,
    redirect_host: str,
    email: str,
    scopes: list[str],
    writes_enabled: bool,
    workspaces: list[dict[str, Any]],
    ticket: str,
    csrf_token: str,
) -> str:
    is_write, level = access_level(scopes, writes_enabled)
    read_scopes = [s for s in scopes if s not in WRITE_OAUTH_SCOPES]
    write_scopes = [s for s in scopes if s in WRITE_OAUTH_SCOPES]
    options = "".join(
        f"<option value='{_e(w['id'])}'>{_e(w['name'])} ({_e(w['slug'])}) · {_e(w['role'])}"
        "</option>"
        for w in workspaces
    )
    write_block = ""
    if is_write and write_scopes:
        write_block = (
            "<label class='check'><input type='checkbox' name='allow_writes' value='on'/>"
            "<span>Also allow it to:<ul>"
            f"{_scope_list(write_scopes)}</ul>Leave unchecked to keep this connection "
            "read-only.</span></label>"
        )
    elif write_scopes:
        write_block = (
            "<p class='muted'>Requested write access is not available on this server; "
            "the connection will be read-only.</p>"
        )
    badge = f"<span class='badge {'rw' if is_write else 'ro'}'>{_e(level)}</span>"
    body = (
        "<h1>Allow access?</h1>"
        f"<p class='muted'>Signed in as {_e(email)}</p>"
        f"<p class='app'><strong>{_e(client_name)}</strong><br/>"
        f"<span class='muted'>will return to <code>{_e(redirect_host)}</code></span></p>"
        "<form method='post' action='/oauth/authorize'>"
        f"{_hidden({'csrf_token': csrf_token, 'step': 'consent', 'ticket': ticket})}"
        "<label for='workspace_id'>Workspace it can access</label>"
        f"<select id='workspace_id' name='workspace_id' required>{options}</select>"
        f"<p>It will be able to:</p><ul>{_scope_list(read_scopes)}</ul>"
        f"{write_block}<p>{badge}</p>"
        "<p class='muted'>You can disconnect it at any time in the admin, on the MCP page.</p>"
        "<div class='row'><button type='submit' name='consent' value='deny'>Deny</button>"
        "<button class='primary' type='submit' name='consent' value='approve'>Approve</button>"
        "</div></form>"
    )
    return _page("Allow access?", body)


def render_message(title: str, message: str) -> str:
    return _page(title, f"<h1>{_e(title)}</h1><p>{_e(message)}</p>")
