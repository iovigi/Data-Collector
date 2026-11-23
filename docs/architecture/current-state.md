# Current State Architecture Audit (Baseline M0)

**Baseline SHA:** `e18eaa61a052ed62666183a5b5f85bf334b8f20b`  
**Branch:** `feat/data-collector-2.0`  
**Audit Date:** 2026-11-23

## 1. Repository Inventory
- `app.py`: Flask application factory (`create_app()`), permissive `CORS(app)`, Flask-RESTX Swagger UI, JWT config with hardcoded fallback secret `'your-secret-key'`, eagerly calls `seed_users()` on import/creation.
- `api/database.py`: `get_db()` creates a new `MongoClient` per call without pooling or lifecycle management.
- `api/utils/db.py`: creates a separate global `MongoClient` at module import time.
- `api/auth/decorators.py`: `auth_required` accepts `X-System-Auth` via plain string equality against `os.getenv('SYSTEM_AUTH_KEY')` (which is `None` if unset, though guarded by `if system_auth_header and ...`), falls back to JWT without RBAC or tenant checks. `jwt_required_with_role` is unused and performs no role check.
- `api/utils/seeder.py`: seeds `admin` / `admin123` on every `create_app()` call.
- `api/routes/auth.py`: `POST /api/login` — no rate limiting, returns `404 User not found` vs `401 Invalid credentials` (user enumeration), no refresh/revocation.
- `api/routes/insert.py`: `POST /api/insert`, `POST /api/bulk_insert` — raw `db[data_type]` access from `type` query param, raw exception strings returned in 500 responses.
- `api/routes/query.py`: `GET /api/query` — `json.loads(value)` allows arbitrary MongoDB operators (e.g. `{"$gt": 25}`, `$where`, `$regex`), arbitrary `type` collection name, offset pagination, only `_id` ObjectId conversion.
- `api/routes/update.py`: `PUT /api/update`, `PUT /api/bulk_update` — raw `db[data_type]`, `$set` with unvalidated client payload, raw exception disclosure.
- `api/routes/delete.py`: `DELETE /api/delete` — hard `delete_one` on arbitrary collection `type`, no soft-delete or confirmation.
- `api/routes/index.py`: `POST /api/create_index` — arbitrary index creation on any collection/field.
- `api/routes/base.py`, `api/models/*`: Flask-RESTX resource base and Swagger models.

## 2. Endpoint Behavior Matrix (Baseline)
| Method & Path | Auth | Input Validation | DB Access | Known Risks |
|---|---|---|---|---|
| `POST /api/login` | None | None (`data['username']` KeyError -> 500) | `get_db().users` | User enumeration, no rate limit, weak fallback JWT secret |
| `POST /api/insert` | `auth_required` | `type` + non-empty JSON | `api.utils.db.db[type]` | Arbitrary collection write, no schema, no tenant isolation |
| `POST /api/bulk_insert` | `auth_required` | `type` + JSON list | `api.utils.db.db[type]` | Arbitrary collection write, unbounded batch size |
| `GET /api/query` | `auth_required` | `type`, `page`, `per_page` | `api.utils.db.db[type]` | Operator injection (`$regex`, `$where`), arbitrary collection read |
| `PUT /api/update` | `auth_required` | `type`, `where_field`, `where_value` | `api.utils.db.db[type]` | Arbitrary collection/field overwrite, no optimistic concurrency |
| `PUT /api/bulk_update` | `auth_required` | `type`, `where_field`, list | `api.utils.db.db[type]` | Unbounded bulk update, no tenant isolation |
| `DELETE /api/delete` | `auth_required` | `type`, `where_field`, `where_value` | `api.utils.db.db[type]` | Hard delete on arbitrary collection |
| `POST /api/create_index` | `auth_required` | `type`, `field` | `api.utils.db.db[type]` | Index explosion / DoS |

## 3. Dependency & License Inventory
- Baseline `requirements.txt`: `flask==3.0.2`, `pymongo==4.6.1`, `python-dotenv==1.0.1`, `flask-cors==4.0.0`, `flask-restx==1.3.0`, `flask-jwt-extended==4.6.0`, `bcrypt==4.1.2`.
- No `LICENSE` file in repository; do not assume OSI-approved open source license without owner confirmation.
- Target runtime: Python 3.13 (3.12+ supported), MongoDB 7+, Redis 7+, official `mcp` Python SDK.

## 4. Risk Register
- **SEC-001**: Hardcoded fallback JWT secret `'your-secret-key'` in `app.py`.
- **SEC-002**: Default `admin/admin123` seeded automatically on app startup in `seeder.py`.
- **SEC-003**: `X-System-Auth` static shared key bypasses user identity and RBAC.
- **SEC-004**: No multi-tenant isolation or collection-level authorization; any authenticated user accesses any MongoDB collection including `users`.
- **SEC-005**: Raw MongoDB query operator injection via `GET /api/query` `value` JSON parsing.
- **SEC-006**: Permissive `CORS(app)` allows all origins.
- **SEC-007**: Raw `str(e)` exception leakage in HTTP 500 responses.
- **SEC-008**: Multiple unpooled `MongoClient` instances (`api/database.py` per-call + `api/utils/db.py` at import).
- **SEC-009**: No login rate limiting, user enumeration (`404` vs `401`), no token revocation/refresh.
- **SEC-010**: No MCP layer yet; future MCP tools must inherit principal permissions and enforce two-stage delete confirmation.
