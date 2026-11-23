# DATA COLLECTOR 2.0 — COMPLETE ADMIN DASHBOARD IMPLEMENTATION MASTER PLAN

**Status:** Implementation specification, not a prompt-only outline  
**Repository:** https://github.com/iovigi/Data-Collector  
**Baseline reviewed:** `main` at `91f1decc4481d44a78f3225de873e3815ec13f18` (2026-11-23)  
**Deliverable:** Fully operational, polished, secure, responsive web administration platform integrated with the existing Data Collector backend  
**Primary language of UI:** English, prepared for future internationalization  
**Implementation agent:** Gemini with optional specialized workers  
**Execution mode:** One end-to-end task; complete all stages automatically and verify every acceptance gate  
**Guiding principle:** No mock business data, decorative buttons, disconnected components, or assumed backend APIs in the finished product.

---

## 0. NON-NEGOTIABLE EXECUTION CONTRACT

You are implementing a production-grade admin dashboard **inside the existing Data Collector repository**. This is a full engineering delivery, not a design exercise or another plan.

1. Read this entire document first; examine the current repository and running API contracts before coding.
2. Perform work continuously across stages S0–S14. Do **not** stop for user approval between stages. Keep stages as internal quality gates, not separate requests.
3. Preserve current Flask, MongoDB, Redis/RQ, MCP, OAuth, REST API, security controls, and existing tests. Never casually rewrite the backend, drop legacy data, or change MCP tools to make UI development easier.
4. Build the web admin as a standalone frontend within `/web` using **Next.js App Router + TypeScript + Tailwind CSS + shadcn/ui primitives + TanStack Query + TanStack Table + React Hook Form + Zod**. Use compatible maintained stable releases resolved and locked at implementation time; document exact choices. No dependency versions are assumed from this specification.
5. Use **npm** with a committed `package-lock.json`, unless the repository already has a documented package-manager standard that should be preserved.
6. The UI must use existing APIs through a typed gateway. Implement small, **properly secured** backend extensions where necessary, rather than fake UI controls or direct browser access to MongoDB.
7. The frontend must **never connect directly to MongoDB, Redis, storage volumes, or service-only secrets**. Server components and BFF routes communicate with REST using user-scoped credentials; no superadmin service token as a universal user proxy.
8. Preserve server-side authorization as the source of truth. UI permission checks affect discoverability and usability, not security enforcement.
9. **No silent failures:** every operation needs a success state, failure state, loading state, and an appropriate recovery path. Clearly distinguish network failures, permission failures, conflicts, validation errors, and expired sessions.
10. Test real UI workflows against a real backend (at least an isolated test environment with real MongoDB + Redis), in addition to component/unit tests.
11. Generate accessible user interfaces suitable for keyboard and screen-reader users; follow WCAG 2.2 AA as the target. Use semantic controls and automated accessibility checks plus manual keyboard testing.
12. All visual content must work in dark and light mode. Do not use low-contrast decorative-only text or rely on color alone for state.
13. Use persistent progress tracking at `docs/admin/IMPLEMENTATION_PROGRESS.md`. Mark stages done **only after** their acceptance tests pass, include evidence (commands/results/commit SHA), and resume incomplete stages if interrupted.
14. Never describe an unimplemented feature as complete. Never claim ChatGPT/Claude live integration validation from dashboard UI alone. Explicitly label external tests that require an actual external account, public domain, or infrastructure.
15. No production deployment, destructive migrations, or changes to real customer data without explicit authorization. Implementation and isolated local/staging validation must proceed without needing intermediate approval.
16. Produce logical atomic commits; run full verification before final handoff. If a genuine external blocker occurs, clearly record it and keep implementing independent work.
17. Document all assumptions and changed backend endpoints. Do not guess API shapes when source code is available; inspect concrete return values and test them.
18. The dashboard is **not only a superadmin console**. It must serve workspace owners/admins/editors/viewers, each with appropriate authorized functionality. A separate platform-superadmin area may be added only with stricter, audited policies.

### Definitions of Done

A feature is done only when the backend behavior exists, the frontend interaction works against the actual backend, permission-denied behavior is correct, error/empty/loading states work, appropriate automated tests pass, and documentation is updated.

### Explicit out of scope for v1 dashboard

- Billing, Stripe, subscriptions, and marketplace features.
- A visual drag-and-drop ETL designer, arbitrary user-supplied Python/JavaScript execution, SQL console, unrestricted MongoDB shell, or remote container control.
- A marketing website, mobile native app, or third-party user tracking/analytics SDK.
- Production infrastructure or OAuth credentials created without operator approval.

---

## 1. VERIFIED REPOSITORY BASELINE AND GAP ANALYSIS

The reviewed backend already contains:

- Flask API under `data_collector/api/v1/`; `create_v1_blueprint()` registers `auth`, `workspaces`, `projects`, `collections`, `records`, `jobs`, `keys`, `audit`, and `m11` blueprints.
- Multi-tenant services and permission model (`data_collector/domain/identities.py`, `policies.py`).
- Authentication: `POST /api/v1/auth/login`, `POST /api/v1/auth/refresh`, `POST /api/v1/auth/logout`, `GET /api/v1/me`.
- Workspaces: list/create/detail and add-or-update member by **principal ID**.
- Projects: list and create; no update/archive routes currently observed.
- Collections: list/create/detail/patch, JSON Schema and allowed searchable/sortable fields.
- Records: create, batch-create, list, search, detail, version-guarded patch, soft delete and restore.
- Jobs: asynchronous import/export, status/result and cancellation.
- API keys: create/list/revoke with scopes and optional collection allowlist.
- Audit: `GET /api/v1/audit?workspace_id=...&limit=...`.
- M11: saved queries create/list/run, webhooks create/list, schema migration preview/apply, workspace usage summary.
- MCP: local stdio and remote HTTP, separate OAuth handling. **Do not repurpose MCP OAuth tokens as browser UI sessions**.
- OpenAPI 3.1 from `data_collector/api/openapi.py`; inspect for incomplete response schemas and supplement specific endpoints as required.
- Docker Compose + Caddy TLS + GitHub Actions.

### Important confirmed gaps for a complete admin UI

These routes were **not present in the reviewed API v1 files** and should be added as explicit backend work, with permissions and tests:

1. List workspace members and their roles with server-resolved safe user profile fields.
2. Invite/add workspace member by email (or explicit invitation model); current `POST /workspaces/{wid}/members` accepts `principal_id`, not an email.
3. Update/remove members and ownership transfer flows; prevent orphaned workspaces.
4. Rename/archive/restore projects and optionally workspaces via controlled lifecycle endpoints.
5. Paginated workspace audit with filters (actor/action/time/decision), not only latest N records.
6. Workspace-level job listing with pagination/filtering (existing job API is primarily by job ID).
7. Webhook detail/update/disable/re-enable/delete and redacted delivery history + resend (current M11 routes only create/list).
8. Saved query rename/update/delete (current routes only create/list/run).
9. API key details/restrictions and rotation workflow if needed; backend currently create/list/revoke. Never return plaintext keys after creation.
10. Explicit permission/capability discovery for the UI, e.g. a `GET /api/v1/workspaces/{wid}/capabilities` endpoint (computed server-side).
11. API-level aggregate dashboard statistics where single existing `/workspaces/{wid}/usage` is insufficient. **Do not manufacture time-series** from counters.
12. An intentionally restricted superadmin operations API if system operations are built; do not expose unscoped tenant data by default.

**Do not** invent these endpoints in frontend code. First implement and test any required backend extensions. For every extension: DTOs, services, policies, repositories, OpenAPI, audit, throttling, integration tests, and migration compatibility.

### Existing API route inventory (verify against current HEAD)

| Area | Method | Current route | UI usage |
|---|---|---|---|
| Session | POST | `/api/v1/auth/login` | Sign in |
| Session | POST | `/api/v1/auth/refresh` | Rotate session token |
| Session | POST | `/api/v1/auth/logout` | Logout and revoke refresh family |
| Session | GET | `/api/v1/me` | Identity and initial access |
| Workspaces | GET / POST | `/api/v1/workspaces` | Switch/create |
| Workspace | GET | `/api/v1/workspaces/{wid}` | Overview/details |
| Members | POST | `/api/v1/workspaces/{wid}/members` | Existing backend requires principal_id |
| Projects | GET / POST | `/api/v1/workspaces/{wid}/projects` | Project list/create |
| Collections | GET / POST | `/api/v1/projects/{pid}/collections` | List/create |
| Collection | GET / PATCH | `/api/v1/collections/{cid}` | Details/schema |
| Records | GET / POST | `/api/v1/collections/{cid}/records` | Browse/add |
| Records | POST | `/api/v1/collections/{cid}/records/search` | Filter/sort/fields/cursor |
| Records | POST | `/api/v1/collections/{cid}/records/batch` | Bulk create |
| Record | GET / PATCH / DELETE | `/api/v1/collections/{cid}/records/{rid}` | View/edit/delete with version |
| Restore | POST | `/api/v1/collections/{cid}/records/{rid}/restore` | Undo soft delete |
| Imports | POST | `/api/v1/collections/{cid}/imports?format=...&dry_run=...` | **Raw file body**, not multipart without backend change |
| Exports | POST | `/api/v1/collections/{cid}/exports` | Schedule export |
| Jobs | GET | `/api/v1/jobs/{jid}` | Job state |
| Jobs | GET | `/api/v1/jobs/{jid}/result` | Authorized download |
| Jobs | POST | `/api/v1/jobs/{jid}/cancel` | Cancel |
| Keys | GET / POST | `/api/v1/keys?workspace_id=...` | Create/list |
| Key revoke | POST | `/api/v1/keys/{kid}/revoke` | Pass workspace_id in body |
| Audit | GET | `/api/v1/audit?workspace_id=...` | Audit summary |
| Saved queries | GET / POST | `/api/v1/collections/{cid}/saved-queries` | Save/list |
| Saved query run | POST | `/api/v1/saved-queries/{sqid}/run` | Query results |
| Webhooks | GET / POST | `/api/v1/workspaces/{wid}/webhooks` | List/create |
| Schema migration | POST | `/api/v1/collections/{cid}/schema-migrations/preview` | Preview |
| Schema migration | POST | `/api/v1/collections/{cid}/schema-migrations/apply` | Apply |
| Usage | GET | `/api/v1/workspaces/{wid}/usage` | Overview |
| Health | GET | `/health/live`, `/health/ready` | Platform status; protect sensitive details as needed |
| OpenAPI | GET | `/api/v1/openapi.json` | API reference |

### Backend request contracts that must be respected

**Login:** `{ "email": "...", "password": "..." }` -> access token + refresh token + `expires_in`.

**Create workspace:** `{ "slug": "customer-data", "name": "Customer Data" }`, slug lower-case 3–64 characters; validate on both tiers.

**Create collection:** `POST /projects/{pid}/collections` with `{ "slug", "schema_json", "searchable_fields", "sortable_fields", "retention_days" }`.

**Create record:** `{ "data": { ... } }` plus optional `Idempotency-Key`.

**Update record:** `{ "patch": { ... }, "expected_version": 3 }` (or `If-Match` header). Treat 409 version conflict as explicit resolve/reload workflow.

**Delete record:** `{ "expected_version": 3 }`, soft delete (not irrevocable wipe).

**Search records:** `{ "filter": SafeQueryAST | null, "sort": [{"field":"created_at","direction":"desc"}], "fields": ["name"], "limit":25, "cursor": null }`. The search response's actual data and next-cursor shape must be inspected and typed from backend; do not assume `total_pages` or use offset pagination.

**SafeQueryAST:** predicate `{ "field":"name", "op":"eq", "value":"Ada" }`; logical `{"and":[...]}`, `{"or":[...]}`, `{"not":{...}}`. Allowed ops `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `exists`, `contains`. Max depth 4, max 20 predicate branches; `in` <=50, `contains` <=200 chars. Use collection allowlists. No arbitrary raw `$` Mongo operators.

**Import:** POST raw bytes to `/collections/{cid}/imports?format=json|jsonl|csv&dry_run=true|false`, include request body and idempotency key. Do **not** send `FormData` unless adding a real multipart endpoint.

**Roles/scopes** in `domain/identities.py`: owner, admin, editor, viewer. Scopes include `workspace:read`, `workspace:manage`, `collection:read`, `collection:manage`, `records:read`, `records:write`, `records:delete`, `jobs:read`, `jobs:create`, `export:read`, `keys:manage`, `audit:read`. Current owner has all scopes; admin has several but **not** `keys:manage` or `workspace:manage`; editor/viewer narrower. Do not label every admin as able to manage API keys or members.

---

## 2. PRODUCT POSITIONING, AUDIENCES AND EXPERIENCE GOALS

Build an operational dashboard for data management across organizations. It must feel like a serious B2B SaaS product (e.g. modern database administration and developer-platform dashboards), not a generated demo.

### User personas

- **Platform operator / superadmin:** monitors infrastructure and manages platform-wide incidents **only when explicitly authorized with separate server-side superadmin privilege**.
- **Workspace owner:** manages workspace members and API keys, resources, records, audit and settings.
- **Workspace admin:** manages projects, collections and records within backend-granted scope; not automatically owner-only controls.
- **Workspace editor:** creates and updates permitted data, imports and exports; limited configuration rights.
- **Workspace viewer:** reads permitted datasets, exports if permitted; cannot modify.
- **Developer/integrator:** manages authorized collections and copies REST/MCP setup snippets; only sees secrets at creation time.

### Product qualities

- Data-intensive and fast, not flashy.
- Efficient navigation at 1280–1920px desktop; usable tablet and mobile layouts without hidden security controls.
- Keyboard-friendly table workflow and discoverable shortcuts.
- Clear tenant context to avoid writing to the wrong workspace.
- Never display data from the previous workspace after switching to a new one.
- Consistent layout, spacing, typography, status indications, and empty states.
- Large datasets handled server-side, not fetched wholesale into browser memory.

### Core navigation

Primary sidebar sections:
1. Overview
2. Projects
3. Collections / Data Explorer
4. Saved Queries
5. Imports & Exports / Jobs
6. API Keys
7. MCP Connections
8. Webhooks
9. Audit Log
10. Usage & Analytics
11. Members & Access
12. Settings
13. Developer / API Reference

Top bar: workspace switcher, current project breadcrumb, global resource search (server-filtered or local accessible metadata only), light/dark mode, help links, user menu/log out, status indicator if relevant.

**Global search is not a search across private records unless an authorized backend search endpoint specifically supports it.** Initial implementation should search accessible workspaces/projects/collections in already-authorized metadata, then progressively add secure search endpoints only if necessary.

---

## 3. UI TECHNOLOGY AND ARCHITECTURE

### Required stack

- Next.js App Router, TypeScript in strict mode.
- React, Tailwind CSS, shadcn/ui-style accessible components based on Radix primitives.
- TanStack Query for client fetching, caching, mutations, invalidation and retries.
- TanStack Table + optional TanStack Virtual for large record grids.
- React Hook Form + Zod for forms and validated inputs.
- Lucide icon set, CSS variables for design tokens.
- Charts: Recharts or equivalent maintained charting library; render charts only from real aggregated data.
- next-intl or a lightweight i18n infrastructure; English copy, translation key files; no need to translate every language now.
- Playwright for browser E2E, Vitest + React Testing Library for unit/component tests, axe-core/Playwright accessibility checks.
- OpenAPI TypeScript generation can assist types; hand-written strict DTOs allowed where OpenAPI responses are not sufficiently specified. Verify types against actual API integration fixtures.

### Directory layout (target)

```text
web/
  app/
    (auth)/login/page.tsx
    (auth)/forgot-password/page.tsx          # only if backend supports reset
    (app)/layout.tsx
    (app)/w/[workspaceId]/overview/page.tsx
    (app)/w/[workspaceId]/projects/page.tsx
    (app)/w/[workspaceId]/projects/[projectId]/page.tsx
    (app)/w/[workspaceId]/collections/page.tsx
    (app)/w/[workspaceId]/collections/[collectionId]/data/page.tsx
    (app)/w/[workspaceId]/collections/[collectionId]/schema/page.tsx
    (app)/w/[workspaceId]/collections/[collectionId]/queries/page.tsx
    (app)/w/[workspaceId]/jobs/page.tsx
    (app)/w/[workspaceId]/keys/page.tsx
    (app)/w/[workspaceId]/mcp/page.tsx
    (app)/w/[workspaceId]/webhooks/page.tsx
    (app)/w/[workspaceId]/audit/page.tsx
    (app)/w/[workspaceId]/analytics/page.tsx
    (app)/w/[workspaceId]/members/page.tsx
    (app)/w/[workspaceId]/settings/page.tsx
    (app)/developer/api/page.tsx
    api/auth/login/route.ts
    api/auth/logout/route.ts
    api/auth/refresh/route.ts                 # server-side only
    api/backend/[...path]/route.ts            # restricted authenticated BFF proxy
    error.tsx
    not-found.tsx
  components/
    layout/
    ui/
    feedback/
    data-grid/
    forms/
    charts/
    auth/
    mcp/
  features/
    auth/
    workspaces/
    projects/
    collections/
    records/
    jobs/
    keys/
    mcp/
    webhooks/
    audit/
    analytics/
    members/
    settings/
  lib/
    api/
      client.ts
      types.ts
      errors.ts
      contracts.ts
      endpoints.ts
    auth/
      session.ts
      cookies.ts
      csrf.ts
    permissions/
      capabilities.ts
    format/
    validation/
    constants/
  hooks/
  styles/
  messages/en.json
  tests/
    unit/
    component/
    e2e/
    fixtures/
  public/
  Dockerfile
  next.config.ts
  package.json
  package-lock.json
  tsconfig.json
  .env.example
  README.md
```

Folder names may be refined if justified. Do not make a giant `components.tsx` or one universal generic page to fulfill all screens.

### Rendering and data flow

```text
Browser (untrusted)
  -> Next.js frontend / BFF (user session + CSRF + request validation)
      -> Flask REST API (user JWT, per-tenant RBAC and service authorization)
          -> application services -> MongoDB / Redis / ArtifactStore

MCP connectors (separate clients)
  -> existing MCP OAuth / API key integration -> same application services
```

No direct MCP calls from the dashboard for basic administration. The MCP UI manages configurations and instructions; REST handles administration.

### BFF vs direct browser API

Use a same-origin **Backend-for-Frontend (BFF)** architecture because auth requires careful token management:

- Browser sends requests only to Next.js same-origin routes.
- Next.js stores refresh tokens and short-lived access tokens only in protected server-side session storage or encrypted, authenticated, HttpOnly cookies with verified security properties. Prefer a server-side session store backed by Redis for revocation and easy refresh; define a session ID cookie.
- Never expose refresh tokens in `localStorage`, `sessionStorage`, Javascript-readable cookies, React context, HTML or logs.
- Browser must not receive backend access tokens when server-side session handling can avoid it.
- BFF authenticates user session, verifies CSRF on state-changing same-origin requests, forwards only authenticated allowed routes and required user-scoped auth to Flask, and strips sensitive headers.
- BFF route must not be an open proxy. Reject non-allowlisted paths and methods; never accept a user-controlled upstream hostname or arbitrary URL.
- BFF must enforce content-type/response-size/upload limits and supported binary streaming. Never buffer arbitrarily large downloads or file uploads into RAM.
- Handle 401 with one guarded refresh attempt, concurrency-safe refresh token rotation (single-flight/lock per session), then fail closed/log out on invalid refresh. Prevent refresh storms.
- Session cookie: Secure in production, HttpOnly, SameSite=Lax or Strict as appropriate, Path=/, unpredictable value. Session expiration and logout invalidation required.
- Decide between same-origin cookie sessions with CSRF token or signed double-submit CSRF; document attack model. Do not assume SameSite replaces CSRF entirely.
- If backend API and frontend share reverse proxy hostname, route `/api/v1/*` and `/mcp` to correct backend/MCP while keeping browser BFF routes under `/api/backend/*` to prevent collisions.
- Forward `X-Request-Id` to UI error surfaces in copyable form; avoid leaking internal stack traces.

### Session lifecycle

1. User navigates to login. If valid authenticated session exists, redirect to permitted landing workspace.
2. User submits email/password. BFF sends credentials over internal HTTPS/private network to Flask `/api/v1/auth/login`.
3. On success BFF persists user-scoped refresh/access tokens server-side with secure session cookie; obtain `/api/v1/me` and accessible workspaces.
4. User selects workspace; UI loads capabilities and accessible resources.
5. Access tokens refresh automatically on server; retry original call once only when safe/idempotent (do not blindly replay POST without idempotency key).
6. On logout, revoke backend refresh family where possible, delete server session and cookie, clear TanStack Query cache, redirect to login.
7. If user loses permission, authorization failures must invalidate relevant cached resources immediately.
8. Session revocation in another tab should propagate via visibility/revalidation or BroadcastChannel without sharing secrets.

### Default user redirection

- No workspaces: `/onboarding/create-workspace` for accounts permitted to create one.
- One workspace: `/w/{workspaceId}/overview`.
- Multiple workspaces: select last authorized workspace where persisted preference is safe, otherwise workspace picker.
- Unknown or inaccessible workspace in URL: clear stale selection and show not-found/permission page; do not fall back to another workspace while preserving old collection IDs.

---

## 4. VISUAL SYSTEM — REQUIRED IMPLEMENTATION DETAIL

### Visual identity

Professional, calm enterprise look: neutral stone/slate surfaces, primary indigo/blue accent, restrained status colors, strong typography and compact data density. No oversized marketing gradients. Distinguish hierarchy using spacing/weight/size, not random bright colors.

Use CSS variable tokens and ensure dark/light parity:

```css
:root {
  --background: 0 0% 100%;
  --foreground: 222 35% 12%;
  --surface: 220 25% 98%;
  --border: 220 16% 88%;
  --primary: 225 76% 52%;
  --primary-foreground: 0 0% 100%;
  --destructive: 0 72% 50%;
  --radius: 0.625rem;
}
/* Dark mode token set must be separately defined, contrast-audited, and tested. */
```

These are starter tokens, not a prohibition on refining visual design. Check text contrast and focus rings programmatically.

### Shell layout

- Desktop sidebar approximately 256px expanded, 72px collapsed, persists state per browser (non-sensitive preference).
- Sticky top header 60–72px, readable breadcrumbs, workspace avatar/icon, user menu.
- Content max-width may be fluid for data explorer and ~1440px for general pages; avoid excessively narrow tables.
- Mobile navigation through accessible slide-over drawer, no hover-only actions.
- Page headings: title, explanatory subtitle, primary action on the right; consistent skeleton placeholders.
- Toasts for transient results, inline field validation, banners for blocking issues, explicit confirmation modal for destructive actions.
- Numeric counters should use locale-aware separators; timestamps UTC from server displayed in user's locale/timezone with tooltip for exact ISO.
- Table default row height 42–48px; compact mode optional; sticky header; horizontal scroll, not broken columns.

### Reusable components

Build and test:

- `AppShell`, `WorkspaceSwitcher`, `ProjectBreadcrumbs`, `SidebarNav`, `UserMenu`, `ThemeToggle`, `GlobalCommandPalette`.
- `PageHeader`, `Breadcrumb`, `StatCard`, `EmptyState`, `ErrorState`, `PermissionDenied`, `SkeletonTable`, `ConfirmDialog`, `DangerDialog`, `CopyButton`.
- `DataTable`, `FilterBuilder`, `ColumnSelector`, `RecordDrawer`, `JsonEditor`, `SchemaEditor`, `PaginationCursorControls`.
- `AsyncActionButton`, `StatusPill`, `AuditEventRow`, `JobProgress`, `ApiKeySecretReveal`, `PermissionBadge`, `CodeSnippet`.
- Forms: field text/select/multi-select/switch, validation messages, primary/secondary actions, unsaved-changes warning.
- Avoid swallowing errors into blank cards, fake data charts, or pointless empty dropdowns.

### Quality and accessibility

- Keyboard focus always visible; icon-only actions labeled.
- Dialog focus trap, Escape behavior, accessible titles/descriptions, confirmed destructive actions.
- Avoid `aria-label` on decorative elements and avoid nested interactive elements.
- Tables accessible; keyboard selection where practical.
- Live regions for operation completion/failure; honor `prefers-reduced-motion`.
- Mobile 375px viewport usable for all workflows (dense tables may scroll horizontally).
- User-provided record content, JSON values, webhook URLs, and audit metadata displayed as text, never `dangerouslySetInnerHTML`.
- Basic UI screenshots and Playwright visual checks for desktop/mobile/light/dark; freeze animation/time fixture where needed.

---

## 5. COMPLETE PAGE / ROUTE SPECIFICATIONS

### 5.1 Sign In and Session Pages

**Route:** `/login`

Elements: brand/logo, sign-in title, email, password reveal toggle, submit/loading state, generic auth error, secure redirect after login. `Forgot password` link **only if a real password reset backend is delivered**; otherwise omit until the appropriate backend work exists.

Requirements:

- Do not reveal whether email exists via login error.
- No 'remember me' checkbox unless session duration semantics implemented.
- Password autocomplete `current-password`, accessible labels.
- Prevent redirect injection: only allow internal verified return paths.
- 429 login limit handling with appropriate retry messaging.
- E2E: correct login, incorrect password, malformed input, expired sessions, logout, back-button after logout.

### 5.2 First-use Onboarding

**Route:** `/onboarding/create-workspace`

- Show concise explanation of workspace/project/collection hierarchy.
- User creates workspace (name/slug validation), first project, optionally first collection with basic JSON schema.
- Wizard progress persists only in safe local UI state; don't create duplicate workspace on network retry.
- Explicit 'Skip for now' only when it leads to an actionable page.
- Show API key/MCP setup recommendations without forcing external secrets.
- E2E: new user -> workspace -> project -> collection -> first record -> dashboard.

### 5.3 Workspace Overview

**Route:** `/w/{wid}/overview`

Sections:
- Summary cards: active records, collections, completed jobs, failed jobs, audit events, using real `/workspaces/{wid}/usage` data.
- Recent projects/collections from authorized endpoints.
- Recent jobs (requires secure paginated new endpoint), recent audit (only when actor has `audit:read`), accessible quick actions.
- Health status: a simple neutral availability indicator using permitted health endpoint; do not expose private infrastructure diagnostics to all members.
- Usage charts only when a time-series endpoint actually exists. Initial v1 may show counts and a note that historical trends require data collection.
- Activity CTA for no workspace/project/collection/records.

Actions: New Project, New Collection, Import Data, Create API Key **only if capabilities allow**.

Acceptance: correct tenant-specific counters; no invented historical metrics; graceful permission-denied sections.

### 5.4 Workspaces and Members

**Routes:** workspace picker + `/w/{wid}/members`

Workspace picker: cards/list, search by name, role indicator, create workspace, accessible switching.

Members page columns: name/email, role, invitation status, added date, last activity if recorded and authorized. Member add via email invitation; role dropdown; remove member; transfer ownership safely; cannot remove last owner; self-removal confirmation.

**Important:** existing backend only supports add member by principal ID. Add real member listing and invitation workflows (see backend section) before completing UI. Do not build a fake local-only member table or expose enumeration of arbitrary users across tenants.

Policy: owner-only workspace management unless backend grants other actors explicit permission. Owners cannot transfer to non-active/unverified accounts without verification.

Acceptance: two users in different workspaces; invite/accept/remove; checks across owner/admin/editor/viewer; never leak unknown users.

### 5.5 Projects Management

**Routes:** `/w/{wid}/projects`, `/w/{wid}/projects/{pid}`

Project list: grid/table toggle, project name, slug, collection count (only if available), updated timestamp (when tracked), search, server-filtered sorting if dataset large. Create dialog with name and auto-suggested editable slug.

Project detail: breadcrumb, collections, basic metadata, edit/archive features **only with secure backend route additions**. Confirm archive and explain effects; archive must not silently delete nested records.

Acceptance: duplicate slug conflict, 403 for viewer create, correct workspace/project membership, inaccessible project returns 404/403 safely.

### 5.6 Collections Management

**Routes:** `/w/{wid}/collections`, `/w/{wid}/collections/{cid}/schema`, `/.../data`

Collection list: by project, slug, schema version, record count only if authorized and available, retention policy, search/sort allowlists, recent activity if available. Creation wizard: select project, slug, JSON Schema from form builder or raw JSON editor, searchable/sortable field selector, retention days, validation preview.

Collection schema detail:
- JSON Schema editor with syntax highlighting and error positions.
- Form-based field definitions (string, number, integer, boolean, date-like strings, arrays/objects) that generate standards-compliant JSON Schema 2020-12. Preserve complex schema constructs in raw mode; do not destructively round-trip unsupported constructs.
- Show required fields, constraints, searchable/sortable field allowlists.
- Schema migration preview, incompatible record counts/examples only when authorized, explicit apply confirmation.
- Schema version and audit history where backend provides it.

Acceptance: invalid JSON, invalid JSON Schema, schema evolution preview, safe no-op preview, unchanged data after failed migration, read-only viewer cannot save.

### 5.7 Data Explorer — PRIMARY PRODUCT SURFACE

**Route:** `/w/{wid}/collections/{cid}/data`

This must be a true interactive record browser, not a static JSON list.

Layout:

- Collection breadcrumb, schema badge, record count from authorized count endpoint if available.
- Search/filter toolbar, saved queries dropdown, refresh, column selection, density, export, import, new record button.
- Server-driven table with columns derived from JSON Schema, plus stable metadata (`id`, `version`, `created_at`, `updated_at`) in optional view.
- Cells render string, number, boolean, date, array/object preview, null, missing fields clearly.
- Click row to open record drawer with structured field form and raw JSON tabs.
- Row action menu: View, Edit, Copy ID, Duplicate, Soft Delete; only show allowed actions.
- Multi-select for permitted batch operations. Existing backend batch supports **create only**; implement backend bulk update/delete carefully if offering those actions, else do not show them.
- Record drawer has copyable record ID, version, source and audit history if supported, and close/unsaved changes handling.

#### Server pagination

Use keyset/cursor pagination from backend. Keep an in-memory cursor stack for `Previous` navigation and the returned `next_cursor` for `Next`; reset cursors on sort/filter/collection change. Do not promise random page jumping with page numbers unless backend supports it.

Large table optimization: server-limited 25/50/100, virtualize rows only as needed, avoid fetching all records into browser.

#### Filter Builder UX

- Simple row: Field dropdown (only searchable), operator dropdown based on field type, typed value control, Add condition.
- Logical groups: AND/OR; optional NOT; nested max depth four.
- Supported ops exactly `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `exists`, `contains`.
- Provide human-readable summary and optional safe DSL JSON preview.
- Validate max 20 predicates, 16 KiB filter size, <=50 values in `in` and <=200-character contains; no unsafe MongoDB operators.
- Date comparisons send validated ISO values consistent with backend schema semantics.
- `Reset filters` clears both UI and cursor.

Example query:

```json
{
  "filter": {"and": [
    {"field": "country", "op": "eq", "value": "Bulgaria"},
    {"field": "score", "op": "gte", "value": 80}
  ]},
  "sort": [{"field": "created_at", "direction": "desc"}],
  "limit": 25
}
```

#### CRUD editor

- Use schema-generated field widgets where possible, with JSON fallback.
- New record sends `{ "data": ... }` with fresh idempotency key per intended submission.
- Edit uses `{ "patch": ..., "expected_version": record.version }`.
- JSON editing should make the actual patch semantics clear. If backend treats patch as merge or replacement at certain levels, mirror precisely and document it.
- On 409 version conflict: show 'Someone updated this record', display current server version, enable reload and manual conflict resolution. Never silently overwrite.
- Delete is soft-delete with record ID/name confirmation where appropriate, expected_version, toast and undo/restore affordance. Avoid delete on double click.
- Restore only on server support for listing deleted records; if there is no secure deleted-list endpoint, add one or support restore only from a known deleted record detail where permitted. Do not show an empty 'Trash' tab that cannot load.
- Duplicate must strip metadata/IDs and revalidate against schema.

#### Import and Export from Data Explorer

- Import wizard: file picker, format CSV/JSON/JSONL, schema checks, maximum size, dry-run validation, row-level errors, submit and job navigation. Backend raw-byte upload contract must be preserved.
- Export dialog: format, current filter, inclusion of selected columns if backend supports them (otherwise remove), schedule, progress, download result.
- Never insert CSV formula-unsafe content into an HTML table via raw HTML.

Acceptance E2E: build collection, add 3 records, filter, sort, paginate, edit with version, conflict handling, soft delete and restore, import dry-run and import, export and download.

### 5.8 Saved Queries

**Route:** `/w/{wid}/collections/{cid}/queries`

List saved queries by name, filters, sort, columns, creation data if available; run a query in Data Explorer; save current query; edit/rename/delete with backend extensions. Show permission-aware actions.

Important: saved queries should not become a way to bypass field allowlists or a user's current access. Every run re-checks current privileges and collection authorization.

### 5.9 Import / Export / Background Jobs

**Route:** `/w/{wid}/jobs`

- Tenant-filtered paginated jobs with type/import/export, collection, initiator, state, progress counts, created/started/finished times.
- Filter by status/type/date; view details and row errors.
- Cancel only cancellable jobs and with permission.
- For exports: authorized download via BFF streaming; verify digest where practical and never reveal internal filesystem path.
- Poll pending/running jobs with capped interval and exponential backoff, stop polling for terminal jobs and hidden tabs. If adding SSE, secure the channel.
- Show truthful progress: queued/started/processing/completed/failed/cancelled. No fabricated percentage if worker cannot provide total.
- Frontend must not require undocumented job listing; implement tenant-safe list endpoint first.

### 5.10 API Keys & Developer Credentials

**Route:** `/w/{wid}/keys`

- List key name, prefix, scopes, collection restrictions, expiration, creation, last-used if provided, revoked status. Never display key hash or recover plaintext.
- Create form: name, expiry, grouped scopes with explanations, collection allowlist selector, least-privilege defaults.
- Secret reveal **once** after creation in a modal; copy-to-clipboard and explicit acknowledgement. Never persist key to browser storage, query string, telemetry, or console.
- Revoke confirmation with impact warning. Rotating keys should be create-new / update clients / revoke-old with clear guidance; add backend rotation endpoint only if necessary.
- Block UI for owner-only `keys:manage` where current policies dictate. Do not treat `admin` label as a permission grant.
- E2E: owner can issue and revoke; admin/editor/viewer cannot with current role matrix; key disappears/marks revoked; revoked key cannot access API.

### 5.11 MCP Connections Center

**Route:** `/w/{wid}/mcp`

This is a connection setup/admin page, **not** an LLM chat window. Show:

- Server endpoints / remote MCP URL (from safe backend public configuration, not a hardcoded example domain).
- Copy configuration for Claude Desktop/Claude Code stdio; safe placeholder `DATA_COLLECTOR_API_KEY` instructions; never embed actual API key outside one-time reveal.
- Steps for ChatGPT custom MCP, Claude remote MCP, OpenAI API remote MCP, and developer SDK clients.
- Clear labels for `stdio` (local process), `Streamable HTTP` (remote URL), OAuth vs API key.
- Required OAuth scopes and read-only default; guidance to use least-privilege keys.
- Safe diagnostics: server availability, GET protected-resource metadata, tool discovery only through a properly scoped server-side diagnostics endpoint; never invoke powerful MCP tools using platform superadmin credentials just to 'test connection'.
- Client compatibility badges only when verified through supported test evidence. For manual ChatGPT/Claude verification, provide checklist and mark 'Not verified' until tested.
- Example configuration must reflect the real `dc-mcp-stdio` executable and required environment variables, with secrets as placeholders.
- Buttons: Copy URL, Copy config, View docs, Test server metadata (actual action), Create scoped key (navigate to keys), View session scopes. No fake 'Connected' claim merely because the health endpoint returns 200.

### 5.12 Webhooks

**Route:** `/w/{wid}/webhooks`

- List name, URL hostname (not embedded secret query params), events, status, deliveries/errors, last delivery.
- Create endpoint with event multi-select, HTTPS URL validation, generated signing secret revealed once, no long-lived secret in logs.
- Details: rotate signing secret, edit URL/events, enable/disable, delete and redacted delivery attempts if backend supports extension.
- Deliveries: status, HTTP status, attempt timestamps, response-size capped error, retry policy, manual resend authorized with idempotency.
- Security: keep existing SSRF/DNS pinning protection, disable redirects, reject local/private targets, signed HMAC payload; no browser direct webhook test requests.
- New endpoints require explicit auth, tenancy, audit, and integration tests.

### 5.13 Audit Log

**Route:** `/w/{wid}/audit`

- Table: timestamp, actor identifier, action, target, allow/deny, request ID if available.
- Filters: time range, actor, action, result, resource type. Server pagination.
- Expand row for scrubbed safe metadata; never reveal credentials, raw tokens, webhook secrets or secret-bearing request payloads.
- Export audit only if explicit authorized backend support and retention rules exist.
- Viewer/editor without `audit:read` sees a permission page, not an empty log.
- Add paginated filter endpoint preserving server-side `audit:read`.

### 5.14 Usage & Analytics

**Route:** `/w/{wid}/analytics`

- Current counters from `/workspaces/{wid}/usage`: active records, collection count, completed/failed jobs, audit events.
- If time-series are desired, add proper daily aggregated usage records with retention and new endpoints; no fake historical chart from a snapshot.
- Optional charts: daily record creation, import success rate, MCP tool usage, API request rate, storage growth. Include data source, aggregation window, timezone and permissions.
- Exclude sensitive telemetry from broad workspace roles when not authorized.
- Loading/empty states and honest 'history not available' states.

### 5.15 Settings

**Route:** `/w/{wid}/settings`

Sections:
- Workspace profile (name/slug), retention/security overview.
- Members/access link.
- Collection schemas, webhook config, project lifecycle settings.
- Integration docs and environment-specific configuration guides (read-only server runtime values unless safe admin APIs implemented).
- Danger zone: archive workspace, transfer ownership, destructive operations only with deliberately implemented backend and double confirmation.

Do not create UI toggles for server environment variables (OAuth mode, JWT secret, Mongo URI, private keys) unless a secure dedicated operator-controlled configuration service is implemented. Infrastructure secrets are not editable from ordinary workspace settings.

### 5.16 Platform Operations (separate privileged area)

**Route:** `/system` — optional in initial release, implement only if backend superadmin endpoints are carefully designed.

- Real platform status, Mongo/Redis availability, RQ queues, dead jobs, aggregate usage and version/build information.
- Maintenance/backup alerts, not arbitrary restart/execute shell controls.
- Strong explicit server-side `is_superadmin` enforcement and audit for each endpoint; no possibility to switch into another tenant merely by changing URL.
- Separate navigation, clear 'Platform administration' header; avoid mixed tenant context.
- If safe endpoints cannot be completed, omit this area from v1 and label as future work, but deliver all tenant admin screens.

---

## 6. BACKEND EXTENSIONS — SPECIFIC REQUIRED API WORK

Before implementing missing UI controls, add the following API work in `data_collector/api/v1/`, corresponding application services and repositories. Use `/api/v1/` and current serialization/error envelopes. The exact request/response DTOs below are **proposed new contracts**, not claims about the current repository.

### 6.1 Membership and invitations

Proposed:

```http
GET    /api/v1/workspaces/{wid}/members?limit=50&cursor=...
POST   /api/v1/workspaces/{wid}/invitations
GET    /api/v1/workspaces/{wid}/invitations
POST   /api/v1/invitations/{invitationId}/accept
POST   /api/v1/invitations/{invitationId}/revoke
PATCH  /api/v1/workspaces/{wid}/members/{principalId}
DELETE /api/v1/workspaces/{wid}/members/{principalId}
POST   /api/v1/workspaces/{wid}/transfer-ownership
GET    /api/v1/workspaces/{wid}/capabilities
```

Proposed invite body: `{"email":"colleague@example.com","role":"editor"}`. Do not expose email existence. Store only token hash for invitation links, TTL (e.g. 7 days), single-use consumption, audit. Email sending requires configured SMTP/provider, robust queue/outbox and tests; if email provider is not configured, fail explicitly and provide a secure admin-only invitation link workflow that does **not** pretend an email was sent. Rate-limit invites. Preserve owner role constraints and last-owner protection. A user must not gain membership just by knowing another user's principal ID.

Member list response example:

```json
{
  "items": [
    {"principal_id":"...", "email":"masked-or-authorized@example.com", "role":"editor", "joined_at":"2026-11-23T00:00:00Z"}
  ],
  "next_cursor": null
}
```

Capabilities example:

```json
{
  "workspace_id":"...",
  "role":"owner",
  "scopes":["workspace:read","workspace:manage","collection:read","keys:manage"],
  "features":{"can_manage_members":true,"can_create_keys":true,"can_manage_webhooks":true}
}
```

Values must be computed from the actual policy engine and active actor/key restrictions, not hardcoded per-role client guesses.

### 6.2 Workspace/project lifecycle

```http
PATCH /api/v1/workspaces/{wid}
POST  /api/v1/workspaces/{wid}/archive
POST  /api/v1/workspaces/{wid}/restore
GET   /api/v1/projects/{pid}
PATCH /api/v1/projects/{pid}
POST  /api/v1/projects/{pid}/archive
POST  /api/v1/projects/{pid}/restore
```

Add optimistic concurrency for lifecycle changes if warranted, explicit archive semantics, audit, unique per-tenant slug indexes, and tenant predicates. Prefer archive over hard delete. Define behavior for active jobs/webhooks on archive.

### 6.3 Job list, audit pagination and record trash

```http
GET /api/v1/workspaces/{wid}/jobs?status=...&type=...&limit=50&cursor=...
GET /api/v1/workspaces/{wid}/audit?actor_id=...&action=...&from=...&to=...&limit=50&cursor=...
GET /api/v1/collections/{cid}/records/trash?limit=25&cursor=...
```

All use safe cursor-based pagination, tenant filtering and correct read scopes. Do not reuse generic unscoped MongoDB find operations. Limit user-controlled sort/filter fields and query execution time. Do not count enormous collections inefficiently on every page render.

### 6.4 Saved queries and webhook management

```http
GET    /api/v1/saved-queries/{sqid}
PATCH  /api/v1/saved-queries/{sqid}
DELETE /api/v1/saved-queries/{sqid}
GET    /api/v1/workspaces/{wid}/webhooks/{hookId}
PATCH  /api/v1/workspaces/{wid}/webhooks/{hookId}
DELETE /api/v1/workspaces/{wid}/webhooks/{hookId}
POST   /api/v1/workspaces/{wid}/webhooks/{hookId}/rotate-secret
GET    /api/v1/workspaces/{wid}/webhooks/{hookId}/deliveries?limit=50&cursor=...
POST   /api/v1/workspaces/{wid}/webhooks/{hookId}/deliveries/{deliveryId}/retry
```

Maintain HMAC signing, no secret retrieval after creation/rotation, outbound SSRF protections and rate limits. When saved query changes, verify schema and allowlists again. All new mutations must be audited.

### 6.5 Dashboard aggregates / trends

```http
GET /api/v1/workspaces/{wid}/dashboard/summary
GET /api/v1/workspaces/{wid}/analytics/series?metric=records_created&from=...&to=...&interval=day
```

`summary` should aggregate existing verified counts and recent limited resources efficiently. `series` must return real measured or stored metrics. If a timeseries data source is not yet built, implement it before exposing the chart or skip chart entirely until available.

### 6.6 UI-specific security controls

- User lookup/invitation restricted to workspace management, prevent enumeration.
- Capability endpoint bound to effective scopes, including current key restrictions and collection allowlists.
- Admin-friendly errors with stable codes and request IDs.
- Refreshed JSON Schema/OpenAPI definitions, response shapes, contract tests.
- Session BFF isolates credentials; backend remains authorization authority.
- No `admin=True` query params, no `X-System-Auth` return, no SSRF-capable backend proxy.

---

## 7. ROLE/FEATURE MATRIX (DERIVE FROM BACKEND)

Baseline policies observed in `domain/identities.py`:

| Feature | Owner | Admin | Editor | Viewer |
|---|---:|---:|---:|---:|
| Read workspace and collections | Yes | Yes | Yes | Yes |
| Create/edit projects and collections | Yes | Yes | No | No |
| Read records | Yes | Yes | Yes | Yes |
| Create/edit records | Yes | Yes | Yes | No |
| Soft delete records | Yes | Yes | No | No |
| Create/cancel jobs where allowed | Yes | Yes | Yes | No |
| Read export/job results | Yes | Yes | Yes | Yes |
| Read audit log | Yes | Yes | No | No |
| Manage API keys | Yes | No | No | No |
| Manage workspace members | Yes | No | No | No |

**Warning:** This is a derived baseline. The actual enforcement may depend on `Actor.scopes`, workspace membership, collection allowlists, and resource-specific checks. The dashboard **must** consume effective capabilities and treat the backend as final authority. New webhook/saved query management policies should be explicitly documented and tested; do not assume `collection:manage` grants global workspace management.

Tests needed: every role against every server action; cross-tenant ID substitution; revoked key; dropped membership; stale UI access; API-key collection allowlist; no hidden API route bypass.

---

## 8. CLIENT STATE, CACHE, ERRORS AND PERFORMANCE

### Query keys

Use tenant-scoped keys, for example:

```ts
['workspace', workspaceId]
['capabilities', workspaceId]
['projects', workspaceId, filters]
['collections', workspaceId, projectId]
['records', workspaceId, collectionId, filterHash, sortHash, cursor, limit]
['jobs', workspaceId, status, cursor]
['audit', workspaceId, filters, cursor]
['keys', workspaceId]
```

On workspace switch, clear tenant-sensitive queries or ensure no cross-tenant cache reuse; cancel in-flight requests associated with old tenant and reset record drawers. On logout clear all user data in query cache.

### Error handling

Use a typed `ApiError` with `status`, `code`, `message`, `details`, and `requestId`. Map:

- `400/422`: display field validation and fix request.
- `401`: refresh/session expired -> login; no infinite retry.
- `403`: permission-denied page/action; no data leak.
- `404`: resource unavailable/inaccessible; do not confirm existence.
- `409`: concurrency/duplicate/slug conflict, show tailored resolution.
- `413`: uploaded file too large.
- `429`: rate limited; display retry message and backoff.
- `500+` and timeout: actionable retry, request ID for support; redact internals.

Never assume every API success response is HTTP 200 (create 201, job 202, batch 207).

### Performance budgets (targets; measure in CI/staging)

- UI navigation feels responsive after hydration and warmed cache.
- Largest initial JS bundles kept lean using route-level code splitting.
- p75 LCP target <=2.5s on representative desktop test environment and realistic dataset; if environment cannot meet this, report reproducible metrics and optimization backlog.
- Interactive table handles thousands/millions of backend records without loading everything client side.
- Debounce search ~250–350ms where applicable and cancel stale requests.
- Use loading skeletons, not shifting blank layouts.
- Respect API rate limits; no background polling across every page.
- Download/import streaming or bounded buffering with operational limits; never unbounded memory allocation.

---

## 9. DESIGN/IMPLEMENTATION DETAILS THAT MODELS OFTEN GET WRONG

**MUST NOT:**

- Produce a beautiful mock dashboard with hardcoded counters, placeholder rows, or fabricated charts.
- Create 'coming soon' links for required features and call complete.
- Give all workspace admins owner permissions in UI or backend.
- Store JWT refresh token in localStorage.
- Build a catch-all BFF proxy that accepts arbitrary paths/hosts without route allowlisting.
- Break MCP HTTP routes or expose OAuth key material to frontend.
- Use direct `fetch` to MongoDB or unrestricted aggregation commands.
- Leak API keys in server logs, screenshot tests, Sentry payloads, client state, URL, clipboard history beyond explicit user copy.
- Retry non-idempotent writes automatically after uncertain network failure without idempotency semantics.
- Use offset/page pagination against a keyset cursor API.
- Assume users can be invited by email through a principal-ID-only existing endpoint.
- Send `multipart/form-data` to the raw-byte import endpoint.
- Make `.env` from secrets part of Git.
- Open MongoDB/Redis publicly in Compose.
- Mark every backend scope available to owner/admin/editor without checking actual scope intersection.
- Regenerate `package-lock.json` non-deterministically each CI run.
- Add mock services or `TODO` placeholders to pass tests while features remain missing.
- Build table columns solely from first row (schemas may include optional fields absent in first row).
- Perform destructive schema migration automatically on Save.
- Confuse `schema_json` request key with internal `json_schema` Pydantic field name.
- Allow cross-workspace browser back navigation to display stale record data.

**MUST:**

- Create actual routes/components/tests for each required screen.
- Use feature-specific API modules with typed request/response validators and error contracts.
- Keep workspace/project/collection selection explicit and visible.
- Validate the current API response shape in integration tests instead of inventing it.
- Use stable keys and accessible labels for table actions.
- Use correct `expected_version` for update/delete operations.
- Check idempotency and double-submit behavior.
- Build unit, integration and Playwright tests that run with reproducible fixtures.
- Document environment and startup commands, including frontend/container reverse proxy routing.

---

## 10. SECURITY THREAT MODEL AND REQUIRED TESTS

### Authentication and sessions

- Sessions must be opaque to browser JS, short-lived server access tokens plus carefully rotated refresh tokens, complete logout revocation.
- Password flows protected from brute force via existing backend limits; UI must not expose account existence.
- CSRF protection on BFF state-changing routes (login/refresh/logout/CRUD handling as applicable).
- Block open redirects and untrusted return URL destinations.
- Rate limit/session fixation/replay protection. Session ID regenerate on login.
- Web app must not share OAuth consent/session cookies incorrectly with MCP auth origin.

### Authorization and isolation

- Workspace ID, project ID, collection ID and record ID swapped with another tenant are rejected.
- Cache never mixes users/tenants/roles.
- Capability UI and backend use exact role-scope intersection; a disabled button is never the only enforcement.
- API keys remain restricted by `allowed_collection_ids`.
- Export downloads authorized at execution *and* download time; no path traversal or raw artifact path returned to browser.
- Invitation redemption checked for correct identity, expiration, single-use and role.
- Owner transfer and member removal safeguards.

### Content and injection

- No raw MongoDB operators in filters.
- All JSON display text-escaped; no unsafe HTML injection through collection/record data.
- Prevent spreadsheet formula injection in CSV downloads (backend existing behavior must remain).
- Prevent CSV/JSON import unlimited file memory usage, decompression bombs if supporting zipped uploads, schema-invalid rows.
- Webhook URL SSRF guard with DNS pinning and no redirected private/internal targets.
- JSON schema editing must not execute user-provided JS/code.
- Secure link handling and CSP; use restrictive default headers, avoid unsafe inline scripts where possible.

### Auditing and privacy

- Log who created/changed data, credentials, membership, webhooks, schemas, and deletes; redact secrets and PII where possible.
- Do not send user records into external analytics, error tracking or log enrichment without deliberate policy.
- Retention constraints and backups documented; download endpoints prevent shared caching.

### Required adversarial test examples

1. Alice logs in, loads records in workspace A. Bob switches URL IDs to A and gets 404/403; Bob sees no stale Alice rows.
2. Viewer crafts POST request to create key/record and is rejected by Flask.
3. Admin tries `keys:manage`; denied under current baseline role policy.
4. Revoked API key and revoked session cannot access protected endpoints.
5. A JSON record containing `<script>` displays harmless text.
6. Attempt to submit `{"$where":...}` or forbidden filter field fails.
7. Two concurrent tabs refresh same session; refresh rotation remains valid, no logout loop.
8. 409 on stale record edit preserves user changes in conflict dialog but does not overwrite server.
9. Attacker posts to BFF from cross-origin without valid CSRF token; rejected.
10. User tries to proxy `/api/backend/http://evil.example` or `/api/backend/internal/system`; denied.
11. Import file over maximum size rejected without buffering unbounded data.
12. Webhook to metadata/private host blocked, including redirects and DNS rebinding.
13. Last workspace owner cannot be removed or demoted without safe ownership transfer.
14. Key plaintext cannot be reloaded after creation.
15. Search and exports respect collection allowlist even when IDs are guessed.

---

## 11. DOCKER, REVERSE PROXY AND ENVIRONMENT

Add `web` service to existing Compose configuration, preserving Mongo/Redis and API/MCP services. Route web traffic through Caddy without breaking existing API/MCP OAuth paths.

**Routing proposal, subject to current deployment design:**

- `https://YOUR_DOMAIN/` -> Next.js web service (`web:3000`).
- `https://YOUR_DOMAIN/api/v1/*` -> Flask API (`api:8000`) **only if direct public API is intended**; alternatively keep Flask internal and use BFF, with a separate documented API hostname for external integrators.
- `https://YOUR_DOMAIN/api/backend/*` -> Next.js BFF (under web route).
- `https://YOUR_DOMAIN/mcp*`, `/.well-known/*`, `/oauth/*` -> existing `mcp-http:8001`.
- `https://YOUR_DOMAIN/health/*` behavior explicit to avoid routing ambiguity.

**Do not** create a conflict between `/api/backend/*` and `/api/v1/*`; verify route precedence in Caddy. Prefer one documented domain model and tests on actual proxy.

Suggested environment:

```dotenv
# web/.env.example -- placeholders only
NODE_ENV=development
NEXT_PUBLIC_APP_NAME=Data Collector
DATA_COLLECTOR_API_INTERNAL_URL=http://api:8000
APP_PUBLIC_URL=http://localhost:3000
SESSION_SECRET=GENERATE_STRONG_RANDOM_SECRET
SESSION_REDIS_URL=redis://redis:6379/1
# Client-visible variables must never include private keys or API bearer secrets.
```

- Add multi-stage `web/Dockerfile` and `.dockerignore` (omit `.env`, node_modules, .next caches).
- Web runs non-root, healthcheck, constrained port binding; production defaults behind Caddy TLS.
- Use Docker healthchecks and restart policies; add `web` to internal network.
- Production secret injection via secret manager/environment, not committed files.
- Add `make dev`/scripts or documented commands to run backend + frontend on Windows/Linux/macOS.
- DB/backups unchanged, existing artifact storage persistent.
- Validate TLS, CSP, cookie Secure/SameSite and proxy headers in staging.

---

## 12. TEST STRATEGY AND QUALITY GATES

### Frontend unit/component tests

- UI controls: dialog, filter builder, record editor, schema editor, table sorting, cursor pager, API key reveal, error screens, workspace switcher.
- Form validation and API error mapping.
- Permission gating visual behavior (and backend server-side denial separate).
- Accessibility and keyboard operation.
- Session state and refresh single-flight logic.

### Backend integration tests for new endpoints

- Membership list/invite/accept/update/remove/transfer owner; no last-owner removal.
- Project lifecycle/collection permissions.
- Jobs and audit pagination and filters.
- Trash listing/restore and permission restrictions.
- Saved query/webhook full management and audit.
- Summary/statistics correctness, tenancy, performance bounds.
- Every new endpoint accurately represented in OpenAPI with request/response validation.

### Browser E2E critical paths

1. Login -> workspace creation -> project -> collection -> record -> logout.
2. Return user -> workspace picker -> project browsing -> collection data.
3. Data Explorer filter/AND/OR -> server query -> cursor next/back -> save query -> rerun.
4. Edit version -> conflicting modification -> resolution dialog -> successful save.
5. Owner creates API key -> copy one-time secret -> revoke -> denied on backend.
6. Viewer sees read-only UI and backend rejects crafted mutation.
7. Import CSV dry-run with errors -> correct file -> job completed -> export/download.
8. Member invite / accept / change role / remove across two accounts.
9. Webhook creation, SSRF-invalid URL, update/disable, delivery status with mock external receiver in isolated integration network.
10. Schema preview incompatible -> cannot silently apply; compatible -> explicit apply.
11. MCP connection page generates correct docs/config; metadata test performs real request.
12. Mobile viewport navigation and desktop light/dark screenshots.
13. Session expiration and expired access token refresh -> expected state.
14. Cross-tenant deep link and cached data isolation.

### Required commands / thresholds

```bash
# Backend (existing, retain)
pytest tests --cov=data_collector --cov-report=term-missing
ruff check data_collector tests
mypy data_collector
bandit -r data_collector -ll
pip-audit

# Frontend (scripts must exist; precise script names may differ but documented)
cd web
npm ci
npm run lint
npm run typecheck
npm run test
npm run build
npm run test:e2e
npm run test:a11y

# Deployment (isolated test env)
docker compose config --quiet
docker compose build
docker compose up -d
```

Minimum targets:

- No TypeScript errors, no lint errors and no failing required unit/integration/E2E tests.
- New backend critical services >=85% targeted coverage; report actual aggregate coverage and uncovered risk paths rather than gaming coverage.
- Frontend critical auth, permission, API, record CRUD, and key modules >=80% line coverage where feasible; report measured results.
- Zero known high/critical dependency vulnerabilities (document accepted exceptions with justification and owner), zero outstanding high/critical security defects.
- At least one isolated real MongoDB+Redis E2E environment; mocks are insufficient as sole validation.
- Automated axe scan zero serious/critical violations on sampled routes; keyboard manual checks documented.
- CI branch protection/review recommended; no claim of live deployment unless explicitly tested.

### CI pipeline extensions

Add frontend jobs to `.github/workflows/ci.yml`:

- `web-lint-typecheck-unit-build` uses supported Node LTS, `npm ci`, lint, typecheck, unit, build, lockfile/audit.
- `web-e2e` starts isolated backend + Mongo + Redis + web using Docker/test database, seeds fixtures using documented CLI/API, runs Playwright headless.
- `web-a11y` can be included in E2E; capture artifacts/screenshots on failure and redact secrets.
- Build/publish only on appropriate trusted release workflows; do not put production secrets into pull request jobs.
- Keep existing Python quality + real DB jobs and Docker build passing.

---

## 13. EXACT IMPLEMENTATION STAGES — EXECUTE EVERYTHING IN ONE CONTINUOUS RUN

Track each stage with checklist and evidence. These are **sequential internal stages**, NOT a request to stop after each one.

### S0 — Current repository audit and implementation contract

Tasks:
- Confirm HEAD SHA and read current `README`, `api/v1/*`, `schemas`, `policies`, OpenAPI and Compose.
- Run current backend tests and CI-equivalent checks before changes.
- List all available routes and identify which proposed API extensions are missing or may already have been added.
- Create `docs/admin/architecture.md`, `docs/admin/api-contracts.md`, `docs/admin/IMPLEMENTATION_PROGRESS.md`.
- Record architecture decisions for browser session strategy, BFF/Redis, path routing, and permission discovery.

Gate: documented decisions, baseline tests, route gap checklist; no speculative endpoints.

### S1 — Backend prerequisite endpoints

Tasks:
- Implement capabilities + member management/invitations.
- Implement project/workspace lifecycle where required.
- Implement paginated jobs/audit/trash and saved-query/webhook edit/delete/delivery endpoints.
- Implement real dashboard summary/analytics endpoint only where warranted.
- Update Pydantic models, repositories, service policies, audit, OpenAPI and tests.

Gate: each new endpoint is protected, documented, tenant-safe, and integration-tested. Existing MCP behavior unchanged.

### S2 — Frontend foundation and design system

Tasks:
- Create Next.js TypeScript app and pinned lockfile under `web/`.
- Tailwind/shadcn primitives, tokens, light/dark themes, responsive shell, sidebar/topbar/layout components.
- Set up lint/typecheck/unit/Playwright/axe and one verified CI build.

Gate: application compiles, shell accessible, no mock dashboard marked finished.

### S3 — Secure BFF, login and session lifecycle

Tasks:
- Implement server session store, cookie rules, CSRF, login/logout/refresh and typed allowlisted proxy.
- Add `/me` and user identity state, route protection, refresh single-flight, lost-permission handling.
- E2E tests for login/logout, session expiry, cross-origin CSRF and forbidden proxy routes.

Gate: authentication/security E2E passes; no browser-visible refresh token.

### S4 — Workspace onboarding and navigation

Tasks:
- Workspace switcher, project breadcrumb, empty workspace onboarding and current tenant capability loading.
- Build workspace creation, project creation, initial collection wizard.

Gate: first-time user can create workspace/project/collection; switching clears old tenant data.

### S5 — Overview, projects and collections

Tasks:
- Build overview with truthful counters, project pages and collection list/create/details.
- Implement all loading/errors/empty states and permissions.

Gate: no fake metrics, real backend writes and updates.

### S6 — Data Explorer and record editing

Tasks:
- Schema-driven table, cursor pagination, filter builder, projections/sort, row drawer, raw JSON editor.
- Create/update/version conflict/delete/restore workflows.
- Saved table preferences (non-sensitive), permission checks, stable cache keys.

Gate: full CRUD/filter/pagination/conflict E2E succeeds against backend.

### S7 — Imports, exports and jobs

Tasks:
- Raw file upload, dry-run, errors, job tracking, exports, secure downloads/cancel.
- Add proper job list UI and backend support.

Gate: genuine import/export through real worker in isolated environment; no fake progress.

### S8 — Members, roles, API keys

Tasks:
- Member listing/invite/roles/removal with ownership constraints.
- API key create/reveal-once/list/revoke, scope explanation, collection restriction.

Gate: role matrix integration tests pass, no secret leaks.

### S9 — MCP Connections Center

Tasks:
- MCP URL/status/setup docs and copy buttons; stdio and remote guides.
- Secure optional metadata diagnostic.

Gate: configuration matches running services and actual supported transport; no false connected status.

### S10 — Saved queries, webhooks and schema migration

Tasks:
- Full saved query management, webhook management and deliveries, schema editor/preview/apply.

Gate: CRUD actions backed by real secure endpoints; SSRF and migration checks pass.

### S11 — Audit, analytics and settings

Tasks:
- Audit filtering/pagination, usage dashboard, settings/lifecycle where supported.
- If system superadmin area is included, build dedicated authorization and test it; otherwise explicitly defer and hide route.

Gate: only real data, correct permissions and production-safe admin controls.

### S12 — Accessibility, design polish and resilience

Tasks:
- Dark/light/mobile polish, responsive shell, visual consistency, keyboard paths, notifications and empty states.
- Session/rate-limit/network recovery testing; performance profiling.

Gate: screenshots inspected, accessibility tests pass, workflows remain functional on 375px and desktop.

### S13 — Docker, Caddy, CI and production packaging

Tasks:
- Web Dockerfile, Compose service, Caddy routing, secret setup, docs and CI jobs.
- Ensure backend REST and MCP routing coexist; no public Mongo/Redis ports.
- Generate staging/production deployment runbook and rollback plan.

Gate: clean `docker compose build/up`, HTTP smoke tests, reverse proxy route tests, complete CI.

### S14 — Final release verification and handoff

Tasks:
- Run full frontend/backend/real database/E2E/security/a11y checks.
- Inspect all pages in browser and capture screenshots in two themes and mobile.
- Audit every actionable button for implementation; remove dead controls.
- Verify tenant isolation, session security, no secret exposure, and no MCP regressions.
- Update README and write `docs/admin/PRODUCTION_READINESS_REPORT.md`.
- Create CHANGELOG entry and PR/review-ready commits.

Gate: all mandatory acceptance criteria pass; outstanding operator-dependent checks clearly separated.

---

## 14. TRACEABILITY MATRIX — FEATURE -> BACKEND -> TEST

| Feature | Backend foundation | Required UI test |
|---|---|---|
| Login/logout | `/auth/login`, `/auth/refresh`, `/auth/logout`, `/me` | Auth and expiry E2E |
| Workspace switcher | `/workspaces` | Tenant cache isolation |
| Member management | New `/members` + `/invitations` | Invite/change/remove permissions |
| Projects | `/workspaces/{wid}/projects`, new lifecycle routes | Create/edit/archive |
| Collections | `/projects/{pid}/collections`, `/collections/{cid}` | Create/schema validation |
| Data Explorer | `/collections/{cid}/records/search` | Filter/sort/cursors |
| Record CRUD | `/records`, `/records/{rid}` | Create/update/409/delete |
| Trash | New `/records/trash` + existing restore | Restore/tenant scope |
| Import | `/imports` raw body | Dry-run/real import job |
| Export | `/exports`, `/jobs/{jid}/result` | Async export/download |
| Jobs | New workspace jobs list + existing ID endpoints | Cancel/state/filters |
| Keys | `/keys`, `/keys/{kid}/revoke` | Reveal once/revoke |
| MCP setup | Existing MCP services/metadata | Actual URL and config |
| Webhooks | M11 existing + new management | Create/disable/delivery |
| Saved queries | M11 create/list/run + new edit/delete | Save/run/edit/delete |
| Schema migration | M11 preview/apply | Incompatible preview/confirm |
| Audit | `/audit` plus new paging/filter | Visibility and time filter |
| Usage | `/workspaces/{wid}/usage`, optional series | Real counters only |
| Settings | New secured lifecycle/capability endpoints | Owner vs viewer |

---

## 15. USER ACCEPTANCE SCENARIOS (MANUAL WALKTHROUGH)

### Walkthrough A: New company starts managing leads

1. Visit dashboard; log in as a new authorized user.
2. Create workspace `Acme`, project `Sales`, collection `leads`.
3. Create fields for `company`, `contact_email`, `country`, `score`, `status` using visual schema designer.
4. Create records from form and import CSV using dry-run then actual job.
5. Filter `country=Bulgaria AND score>=80`, sort by creation date.
6. Save filter as `Qualified Bulgaria Leads`.
7. Update a lead; simulate concurrent update and verify conflict handling.
8. Export filtered leads to CSV; download and verify record count and content.

### Walkthrough B: Permissions and external integration

1. Owner invites editor and viewer; both accept.
2. Editor can create/update records, viewer cannot.
3. Owner creates read-only scoped API key limited to `leads` collection; plaintext shown once.
4. Navigate MCP page, copy Claude Code stdio configuration and remote HTTPS instructions.
5. Verify owner can revoke API key and it fails on subsequent API access.
6. Viewer cannot see or invoke key/member management, even via direct URL/API.

### Walkthrough C: Operations

1. Owner views recent jobs and audit events.
2. Creates a webhook for `record.created`, receives signing secret once.
3. Trigger event in isolated test environment and inspect delivery log.
4. Attempt webhook to private IP; validation rejects.
5. Preview incompatible schema change; examine impact before apply.
6. Inspect usage stats; no fabricated historical data appears.

---

## 16. FINAL PRODUCTION ACCEPTANCE CHECKLIST

All mandatory checks below must pass (or be explicitly marked `BLOCKED_EXTERNAL` for operator-only activities, **not** claimed as passed):

- [ ] Next.js admin opens under a documented URL and routes correctly.
- [ ] Login, refresh, logout and redirect behavior verified with real Flask authentication.
- [ ] No refresh token or server secrets in browser-readable storage/code/logs.
- [ ] Workspace owners/admins/editors/viewers see and can perform only authorized operations.
- [ ] Workspaces, projects, collections and first-use onboarding work end-to-end.
- [ ] Members/invitations work with server-side authorization and no last-owner loss.
- [ ] Data Explorer performs real filtered/sorted cursor pagination.
- [ ] Create/update/delete/restore honor schema and optimistic concurrency.
- [ ] JSON Schema editing, preview and apply work with explicit safety checks.
- [ ] Saved Queries create/list/run/edit/delete are fully wired.
- [ ] Import uses real raw bytes and dry-run; job errors visible.
- [ ] Export is secure, downloadable and correctly limited by permissions.
- [ ] Jobs list/filter/cancel works for user's workspace.
- [ ] API keys can be created, shown once, listed and revoked safely.
- [ ] MCP page displays correct HTTP/stdio setup and truthful status.
- [ ] Webhooks have secured management/delivery flows and existing SSRF protection remains intact.
- [ ] Audit log pagination/permissions correct; no leaked secrets.
- [ ] Usage dashboard shows real numbers, not demo data.
- [ ] Settings and dangerous lifecycle operations have working server contracts and confirmation.
- [ ] Every required page has loading, empty, error and permission-denied states.
- [ ] Light/dark themes and desktop/mobile layouts visually reviewed.
- [ ] Keyboard and accessibility gate passes.
- [ ] Frontend `npm ci`, lint, typecheck, unit tests, build and Playwright E2E all pass.
- [ ] Existing Flask/MCP tests, Bandit, pip-audit, mypy, Ruff and Docker checks still pass.
- [ ] CI includes frontend + real DB integration and reports green.
- [ ] Caddy routes `/`, `/api/backend`, `/api/v1`, `/mcp`, `/.well-known`, `/oauth` correctly.
- [ ] Docs include exact local/staging/prod setup, environment variables, reverse proxy, tests and rollback.
- [ ] No unfinished placeholders, fake stats, dead buttons or unsupported claims in final report.
- [ ] Production readiness report distinguishes **STAGING_GO** from **PRODUCTION_GO**.

---

## 17. DOCUMENTATION OUTPUTS

Create or update:

```text
docs/admin/README.md                       # Purpose and navigation
docs/admin/architecture.md                 # Browser -> BFF -> API trust boundaries
docs/admin/api-contracts.md                # Existing/new endpoints and exact DTOs
docs/admin/permissions.md                  # Role/scope matrix and security model
docs/admin/design-system.md                # Tokens, components, responsive behavior
docs/admin/IMPLEMENTATION_PROGRESS.md      # Stage-by-stage completion + evidence
docs/admin/testing.md                      # Unit/integration/Playwright commands
docs/admin/deployment.md                   # Local, staging, production, Caddy
/docs/admin/PRODUCTION_READINESS_REPORT.md # Final evidence and remaining blocks
web/README.md                              # Developer setup
web/.env.example                           # Placeholders only
CHANGELOG.md                               # Actual delivered features
README.md                                  # Link to Admin Dashboard setup
```

Remove any duplicate or mistaken path; keep all admin documents consistently under `docs/admin/`.

---

## 18. REQUIRED FINAL REPORT FORMAT

Once implementation is complete, provide a concise but comprehensive report:

1. **Repository / SHA / branch** and link to commits or PR.
2. **Delivered screens** list, with working routes and descriptions.
3. **Backend API extensions** including auth policies and migration implications.
4. **Session security model**, CSRF and BFF design.
5. **Test evidence:** actual commands, passed/failed counts, measured coverage, screenshots, accessibility and CI links.
6. **Local development commands** verified on a clean environment.
7. **Docker / staging deployment** setup and reverse proxy behavior.
8. **Known limitations**, real external blockers and exact operator actions.
9. **Production verdict:** `NO_GO`, `STAGING_GO`, or `PRODUCTION_GO` with supporting evidence.
10. **No unsupported completion claims.**

**START IMPLEMENTING NOW. READ THE REPOSITORY, RUN THE BASELINE, THEN PROCEED THROUGH S0–S14 IN ONE CONTINUOUS EXECUTION. DO NOT STOP AFTER WRITING A PLAN. DO NOT ASK FOR INTERMEDIATE MILESTONE APPROVAL. BUILD, CONNECT, VERIFY AND DOCUMENT THE ACTUAL APPLICATION.**
