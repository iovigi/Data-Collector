# Admin Dashboard API Contracts

All existing `/api/v1/*` endpoints are preserved. The following extensions were added in Stage S1:

## Capabilities & Membership
- `GET /api/v1/workspaces/{wid}/capabilities` — server-computed role, effective scopes, and UI feature flags.
- `GET /api/v1/workspaces/{wid}/members` — paginated workspace members with resolved email and role.
- `PATCH /api/v1/workspaces/{wid}/members/{principalId}` — update member role (last-owner protected).
- `DELETE /api/v1/workspaces/{wid}/members/{principalId}` — remove member (last-owner protected).
- `POST /api/v1/workspaces/{wid}/transfer-ownership` — transfer workspace ownership.
- `POST /api/v1/workspaces/{wid}/invitations` — create 7-day single-use hashed invitation link.
- `GET /api/v1/workspaces/{wid}/invitations` — list workspace invitations.
- `POST /api/v1/invitations/{invitationId}/accept` — accept invitation with token.
- `POST /api/v1/invitations/{invitationId}/revoke` — revoke pending invitation.

## Lifecycle, Jobs, Audit, Trash & M11 Management
- `PATCH /api/v1/workspaces/{wid}`, `POST /api/v1/workspaces/{wid}/archive`, `POST /api/v1/workspaces/{wid}/restore`
- `GET /api/v1/projects/{pid}`, `PATCH /api/v1/projects/{pid}`, `POST /api/v1/projects/{pid}/archive`, `POST /api/v1/projects/{pid}/restore`
- `GET /api/v1/workspaces/{wid}/jobs?status=&type=&limit=&cursor=`
- `GET /api/v1/workspaces/{wid}/audit?actor_id=&action=&decision=&limit=&cursor=`
- `GET /api/v1/collections/{cid}/records/trash?limit=&cursor=`
- `GET/PATCH/DELETE /api/v1/saved-queries/{sqid}`
- `GET/PATCH/DELETE /api/v1/workspaces/{wid}/webhooks/{hookId}`, `POST .../rotate-secret`, `GET .../deliveries`
- `GET /api/v1/workspaces/{wid}/dashboard/summary`
