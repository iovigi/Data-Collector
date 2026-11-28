export interface MeResponse {
  principal_id: string;
  principal_type: string;
  email: string | null;
  workspace_id: string | null;
  scopes: string[] | null;
}

export interface Workspace {
  id: string;
  slug: string;
  name: string;
  owner_id: string;
  status: string;
  created_at: string;
}

export interface WorkspaceCapabilities {
  workspace_id: string;
  role: "owner" | "admin" | "editor" | "viewer";
  scopes: string[];
  allowed_collection_ids: string[] | null;
  features: {
    can_manage_workspace: boolean;
    can_manage_members: boolean;
    can_create_keys: boolean;
    can_manage_collections: boolean;
    can_delete_collections: boolean;
    can_write_records: boolean;
    can_delete_records: boolean;
    can_create_jobs: boolean;
    can_export: boolean;
    can_read_audit: boolean;
    can_manage_webhooks: boolean;
    can_manage_all_mcp_connections?: boolean;
  };
}

export interface Project {
  id: string;
  workspace_id: string;
  slug: string;
  name: string;
  status: string;
  created_at: string;
}

export interface Collection {
  id: string;
  workspace_id: string;
  project_id: string;
  slug: string;
  schema_json: Record<string, unknown>;
  schema_version: number;
  searchable_fields: string[];
  sortable_fields: string[];
  retention_days: number;
  status: string;
  created_at: string;
  updated_at?: string;
}

export interface RecordItem {
  id: string;
  workspace_id: string;
  project_id: string;
  collection_id: string;
  data: Record<string, unknown>;
  version: number;
  created_at: string;
  updated_at: string;
  created_by: string;
  deleted_at: string | null;
  source?: Record<string, unknown>;
}

export type FilterOp =
  | "eq"
  | "ne"
  | "gt"
  | "gte"
  | "lt"
  | "lte"
  | "in"
  | "exists"
  | "contains"
  | "array_contains"
  | "between";

export type SafeFilterNode =
  | { and: SafeFilterNode[] }
  | { or: SafeFilterNode[] }
  | { not: SafeFilterNode }
  | { field: string; op: FilterOp; value: unknown };

export interface SearchRecordsResponse {
  items: RecordItem[];
  next_cursor: string | null;
  has_more: boolean;
  limit: number;
}

export interface JobItem {
  id: string;
  workspace_id: string;
  initiator_id: string;
  type: "import" | "export";
  state: "queued" | "running" | "completed" | "failed" | "cancelled";
  progress: { processed: number; succeeded: number; failed: number; total: number };
  params: Record<string, unknown>;
  output_ref?: Record<string, unknown> | null;
  errors?: Array<{ row?: number; error?: string }>;
  error_summary?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface ApiKeyItem {
  id: string;
  workspace_id: string;
  principal_id: string;
  name: string;
  prefix: string;
  scopes: string[];
  allowed_collection_ids: string[] | null;
  expires_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
  api_key?: string;
}

export interface AuditEvent {
  id: string;
  tenant: string | null;
  actor: string;
  action: string;
  target: string;
  decision: string;
  request_id: string | null;
  timestamp: string;
  metadata: Record<string, unknown>;
}

export interface WorkspaceMember {
  id: string;
  principal_id: string;
  email: string | null;
  role: "owner" | "admin" | "editor" | "viewer";
  joined_at: string;
}

export interface InvitationItem {
  id: string;
  workspace_id: string;
  email: string;
  role: string;
  status: string;
  created_at: string;
  expires_at: string;
  invite_token?: string;
}

export interface SavedQuery {
  id: string;
  workspace_id: string;
  collection_id: string;
  name: string;
  filter: SafeFilterNode | null;
  sort: Array<{ field: string; direction: "asc" | "desc" }> | null;
  fields: string[] | null;
  limit: number;
  version: number;
  created_at: string;
}

export interface WebhookItem {
  id: string;
  workspace_id: string;
  name: string;
  url: string;
  events: string[];
  status: "active" | "disabled";
  created_at: string;
  signing_secret?: string;
}

export interface WebhookDelivery {
  id: string;
  delivery_id: string;
  webhook_id: string;
  event: string;
  status: string;
  http_status: number;
  created_at: string;
}

export interface DashboardSummary {
  workspace_id: string;
  counts: {
    records_active: number;
    projects: number;
    collections: number;
    jobs_completed: number;
    jobs_failed: number;
    audit_events: number | null;
  };
  recent_projects: Project[];
  recent_jobs: JobItem[];
}

export interface PrepareDeleteCollectionResponse {
  collection_id: string;
  workspace_id: string;
  project_id: string;
  slug: string;
  status: string;
  records: { active: number; trashed: number; total: number };
  saved_queries: { count: number; items: Array<{ id: string; name: string }> };
  active_jobs: { count: number; items: Array<{ id: string; type: string; state: string }> };
  api_keys_restricted_to_collection: number;
  confirmation_token: string;
  expires_in_seconds: number;
  correlation_id: string;
}

export interface DeleteCollectionResponse {
  collection_id: string;
  slug: string;
  deleted: boolean;
  correlation_id: string;
  records_deleted: number;
  saved_queries_deleted: number;
  jobs_cancelled: number;
  api_keys_detached: number;
  idempotency_keys_deleted: number;
}

export interface McpToken {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  workspace_id: string;
  principal_id: string;
  expires_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
  token?: string;
  read_only?: boolean;
}

export interface McpGrant {
  id: string;
  client_id: string;
  client_name: string;
  user_id: string;
  email: string;
  scopes: string[];
  created_at: string;
  last_used_at: string | null;
}

export interface McpConnectionCheck {
  mcp_url: string;
  ok: boolean;
  checks: Array<{ check: string; ok: boolean; detail: string; ms: number }>;
  tools: string[];
}

export interface AggregateMetric {
  op: "count" | "count_distinct" | "sum" | "avg" | "min" | "max" | "p50" | "fill_rate";
  field?: string;
  as?: string;
}

export interface AggregateResponse {
  collection_id: string;
  group_by: string[];
  metrics: Array<{ op: string; field: string | null; as: string }>;
  rows: Array<Record<string, unknown> & { group?: Record<string, unknown>; unknown_fields?: string[] }>;
  truncated: boolean;
  coverage: {
    matched: number;
    unknown: Record<string, number>;
    freshness: { min_created_at: string | null; max_created_at: string | null };
  };
  notes: string[];
}

export interface HistogramResponse {
  buckets: Array<{ bucket: string; start: string | null; count: number }>;
  truncated: boolean;
  coverage: { matched: number; unknown: Record<string, number> };
}

export interface FieldProfile {
  field: string;
  types: Record<string, number>;
  fill_rate: number;
  queryable: boolean;
  groupable: boolean;
  array_item_types?: Record<string, number>;
}

export interface FieldsResponse {
  total_records: number;
  sampled_records: number;
  fields: FieldProfile[];
}

export interface CountBucket {
  value: number | null;
  accuracy: "exact_as_of" | "cached" | "indexed" | "pending" | "unavailable";
  as_of: string | null;
  age_seconds: number | null;
  source: string;
  reason?: string;
}

export interface CollectionCountResponse {
  collection_id: string;
  active: CountBucket;
  trashed: CountBucket | null;
  total: CountBucket | null;
  status: "ready" | "pending" | "unavailable" | "accepted";
  refresh_available?: boolean;
}

export interface BatchCollectionCountsResponse {
  items: CollectionCountResponse[];
}

export interface SearchStatusResponse {
  collection_id: string;
  enabled: boolean;
  backend: string;
  ready: boolean;
  state: string;
  coverage: "none" | "partial" | "complete";
  indexed_records: number;
  as_of: string | null;
  index_generation: string;
  incremental_sync_supported: boolean;
}

export interface FulltextSearchHit {
  record: RecordItem;
  highlights: Array<{ path: string; text: string }>;
  score: number;
}

export interface FulltextSearchResponse {
  result_window_limited?: boolean;
  items: FulltextSearchHit[];
  next_cursor: string | null;
  has_more: boolean;
  index_status: {
    state: string;
    coverage: string;
    indexed_records: number;
    as_of: string | null;
    backend: string;
  };
  result_total: { value: number | null; accuracy: string };
}
