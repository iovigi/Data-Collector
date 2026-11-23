# IIS Deployment Progress — Data Collector 2.0

Checkpointed log of the IIS-native deployment of `data.devart.solutions`. Secrets are never
written here; values below are redacted or described.

## Owner decisions (2026-11-23)

| Question | Decision |
|---|---|
| Redis-compatible store | **Microsoft Garnet** (MIT), localhost-only Windows service with password auth |
| MongoDB | Reuse existing MongoDB 8.2 service `127.0.0.1:27017`, new database `data_collector` |
| First admin | `admin@devart.solutions`; generated password stored in the restricted secrets folder |
| Cloudflare | Owner-managed, Flexible mode accepted for the initial launch; not touched |
| Push | Not authorised; work committed on local branch `deploy/iis-python-native` only |

## Checkpoints

### 1. Discovery — DONE
- Windows Server 2022 Datacenter, PowerShell 5.1, IIS 10.0.
- IIS features installed: Web-Server, Web-CGI (FastCGI), Static Content, Request Filtering,
  HTTP Logging, Management Console, WebSockets. Global modules present: FastCgiModule,
  RewriteModule, iisnode, AspNetCoreModuleV2, ARR (not used by this site).
- 26 existing IIS sites, all `*:80:<host>`; **no binding for `data.devart.solutions`** (no
  collision). One existing FastCGI application (`C:\PHP\php-cgi.exe`), left untouched.
- Python: only a per-user 3.14 under the Administrator profile (unusable by an app pool).
- Node 24.13.0 / npm 11.6.2 (build time only). Git present.
- MongoDB 8.2.3 `127.0.0.1:27017` (+ replica set instance on 27018 for another app); no
  authentication enabled; localhost-only. **No Redis.**
- Ports in use: 25/587/993 (hMailServer), 80 (IIS), 3306, 5432, 8000 (another app), 27017/27018.
- DNS: `data.devart.solutions` already proxied by Cloudflare (104.21.80.234, 172.67.187.164);
  server hosts file maps it to 127.0.0.1. Origin public IP 62.171.134.72.
- Repo `C:\Projects\Data-Collector`, `main` @ `34c5a28`, clean except untracked `deploy.md`.

### 2. Runtime provisioning — DONE
- Python **3.12.10** installed for all users at `C:\Program Files\Python312` (signature
  verified: Python Software Foundation). No PATH/launcher/file-association changes.
- Venv `C:\Projects\Data-Collector\.venv`: project + `dev` + `iis` extras; `pip check` clean.
  wfastcgi 3.0.0, a2wsgi 1.10.10, Flask 3.1.3, mcp 1.30.0, rq 2.12.0, redis 5.3.1, pymongo 4.20.1.
- Baseline backend tests before any change: **45 passed**.
- Garnet **v2.2.9** (`win-x64-based-readytorun`, Microsoft-signed exe) at
  `C:\tools\garnet\2.2.9`; service `DataCollectorGarnet`, auto start, runs as
  `NT SERVICE\DataCollectorGarnet` (virtual account, not LocalSystem); 127.0.0.1:6379,
  password auth, Lua on, AOF + recover. Config with the password lives in the secrets folder,
  not in the service registry parameters. Verified: unauthenticated commands rejected,
  Lua/locks/pipelines work, data survives a service restart.
- Folders under `C:\ProgramData\DataCollector`: `secrets` (inheritance removed:
  Administrators, SYSTEM + per-identity read grants), `artifacts`, `logs`, `backups`,
  `garnet`, `releases`.
- Secrets generated with the OS CSPRNG into `secrets\datacollector.env`: JWT, intent, web
  session, metrics secrets; RSA-3072 OAuth signing key; Garnet password; admin password.

### 3. Application changes — IN PROGRESS (branch `deploy/iis-python-native`)
- Python BFF replacing Next.js server routes (`data_collector/bff`): Redis sessions keyed by
  sha256(session id), `__Host-` HttpOnly/Secure/SameSite=Lax cookies, session-bound CSRF +
  Origin/Referer checks, exact allowlist, in-process WSGI dispatch to `/api/v1` (no network),
  cross-process refresh lock, fail-closed on Redis loss.
- SPA serving with CSP/no-store HTML, immutable hashed assets, known-route fallback only.
- `JOBS_ASYNC`: the API now enqueues imports/exports (previously executed synchronously in
  the request; the worker never received work). Enqueue failure -> job `failed` + 503.
- Windows worker: `SimpleWorker` + `TimerDeathPenalty` (no fork/SIGALRM); hourly Garnet
  BGSAVE (bounds AOF growth) and log retention.
- MCP: stateless JSON Streamable HTTP hosted in-process through an asyncio loop thread +
  a2wsgi; Host/Origin validation bound to the public host; GET/DELETE /mcp -> 405; actor
  resolved per JSON-RPC message from the SDK request context.
- Cloudflare client-IP middleware (only for peers inside Cloudflare ranges).
- Tests: **64 passed** (45 original + 19 new).
