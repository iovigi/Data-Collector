# IIS Deployment Report — Data Collector 2.0

Date / time / timezone: 2026-11-24 ~01:20 (server local, UTC+1)
Repo commit: branch `deploy/iis-python-native` (local, not pushed); live release `20261124-011228-c9eca4d`
Windows Server version: Windows Server 2022 Datacenter (21H2 / 20348)
IIS version: 10.0
IIS site / app pool / identity: `DataCollector` / `DataCollector` (No Managed Code, Integrated, AlwaysRunning, no idle/periodic recycle) / `IIS AppPool\DataCollector`
Deployment folder: `C:\Sites\DataCollector\{wwwroot,releases\<id>,current -> active release}`; data `C:\ProgramData\DataCollector`
Python executable and version: `C:\Program Files\Python312\python.exe` 3.12.10 (per-release venv)
IIS direct FastCGI bridge and version: wfastcgi 3.0.0 (unmaintained upstream — see risks); MCP ASGI app hosted in-process via a2wsgi 1.10.10
Node build-only version: 24.13.0 (Vite 6.3.5 build; no Node process at runtime)
Public hostname: data.devart.solutions
Cloudflare management: OWNER ONLY (not modified by Claude)
Cloudflare mode specified by owner: Flexible (explicitly accepted for initial deployment)

| Gate | Status | Evidence |
|---|---|---|
| Backend/API | PASS | `verify_deployment.py` 53/53 through Cloudflare HTTPS |
| Dashboard UI | PASS | Playwright (Chromium, public HTTPS): 5/5 — dashboard journey, logged-out redirect, logged-in deep-link refresh, cookie flags, mobile viewport + axe |
| Login/BFF/session/CSRF | PASS | __Host- HttpOnly Secure cookies, session-bound CSRF, Origin checks, logout revokes family |
| MongoDB | PASS | shared 127.0.0.1:27017, new DB `data_collector`, indexes created |
| Redis | PASS | Garnet 2.2.9 service (virtual account, auth, AOF); sessions survive restart |
| Python background worker | PASS | `DataCollectorWorker` service; async import + export completed; first job after restart OK |
| IIS direct WSGI hosting | PASS | FastCGI, no reverse proxy, no extra listener |
| MCP HTTP via IIS | PASS | `verify_mcp.py` 29/29: OAuth (DCR, consent+CSRF, PKCE S256), SDK client, 2-user isolation, refresh rotation/replay, revoke |
| Live ChatGPT/Claude MCP | BLOCKED_EXTERNAL_VALIDATION | needs owner to add the connector in their accounts |

Backend tests / count: 66 passed (45 pre-existing + 21 new)
Frontend tests / count: 5 Vitest passed; typecheck + ESLint clean
Playwright tests / count: 5 passed against https://data.devart.solutions (`PLAYWRIGHT_BASE_URL`, `PLAYWRIGHT_HOST_RESOLVER="MAP data.devart.solutions <edge-ip>"`, `E2E_USER_EMAIL/PASSWORD`)
Backups: scheduled task `DataCollector-backup` daily 03:30 as SYSTEM → `C:\ProgramData\DataCollector\backups` (mongodump gzip archive, artifacts zip, env copy; 14-day retention). Restore rehearsal 2026-11-24: 237 documents / 17 collections restored into a scratch DB, all counts matched, scratch DB dropped.
Security / ACL / Host header tests: `.git`, `.env`, `web.config`, sources, maps → 404; foreign Host → not routed to app; secrets folder admin/SYSTEM + per-identity read; release dirs RX only.
IIS website binding and ports: `*:80:data.devart.solutions` only (HTTP, Cloudflare Flexible).
Backup/rollback locations: IIS config backups `appcmd list backup` (`DataCollector-*`); last 3 releases in `C:\Sites\DataCollector\releases`; rollback `deploy\iis\Deploy-DataCollector.ps1 -Rollback`.

## Defects found and fixed during deployment
1. API never queued jobs (imports/exports ran inside the request) → `JOBS_ASYNC` + fail-closed queue.
2. RQ 2.x writes results with Redis Streams; Garnet has no Streams → worker crashed after each job → result records skipped when Streams absent.
3. Garnet hands items to dead `BLPOP` waiters → first job after each worker restart lost → worker uses non-blocking polling (also: stop in ~3 s instead of 30 s).
4. OAuth endpoints returned 500 on malformed JSON / rate limiting → 400/429.
5. Per-release FastCGI registration recycled all IIS sites → stable `current` junction path (2 one-time brief restarts of 3 ASP.NET Core apps on 2026-11-24 00:38 and 00:47; none since).

## Residual risks / limitations
- Cloudflare Flexible: Cloudflare→origin is plain HTTP (owner-accepted). Recommend Full (strict) + origin certificate later.
- Origin reachable directly on 62.171.134.72:80 (no Cloudflare-only firewall rule) — owner decision.
- MongoDB 27017 has no authentication (shared with other apps, localhost only).
- wfastcgi is unmaintained by Microsoft; works on 3.12.10 as tested.
- MCP is stateless JSON-only (no SSE/GET stream); production OAuth accepts https redirect URIs only (loopback clients such as Claude Code / MCP Inspector cannot register).
- Mongo jobs from the two lost test imports remain `queued` in archived test workspaces.
- Backups stay on the same disk; copy `C:\ProgramData\DataCollector\backups` off the server (encrypted) — owner action.
- Test accounts `e2e-owner@` / `e2e-viewer@devart.solutions` remain (passwords in the secrets folder) for re-running the verifiers; disable them if not wanted.

## Cloudflare checklist for the owner
- DNS proxied (already true). Enable **Always Use HTTPS** (currently http is not redirected at the edge).
- Cache rule: bypass cache for `/api/*`, `/mcp`, `/oauth/*`, `/.well-known/*` (currently DYNAMIC).
- Upload limit: Free/Pro plans cap bodies at 100 MB (app limit 50 MB — OK).
- Later: SSL mode Full (strict) with an origin certificate; firewall origin to Cloudflare IP ranges.

STAGING_GO: YES
PRODUCTION_GO: YES (Flexible origin transport owner-accepted)
Next precise operator actions: owner Cloudflare items above; off-server copy of backups; add the MCP connector in Claude/ChatGPT and test it there.
