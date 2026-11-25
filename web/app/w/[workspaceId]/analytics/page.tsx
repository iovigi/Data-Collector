import React, { useMemo, useState } from "react";
import { useParams } from "@/lib/router";
import { useMutation, useQueries, useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import type {
  AggregateMetric,
  AggregateResponse,
  Collection,
  FieldsResponse,
  HistogramResponse,
  Project,
} from "@/lib/api/types";
import { AppShell } from "@/components/layout/AppShell";
import {
  Badge,
  Button,
  Card,
  ErrorState,
  Input,
  PageHeader,
  Select,
  SkeletonTable,
  StatCard,
} from "@/components/ui/primitives";

interface UsageSummary {
  workspace_id: string;
  records_active: number;
  collections: number;
  jobs_completed: number;
  jobs_failed: number;
  audit_events: number;
}

const OPS: AggregateMetric["op"][] = ["count", "fill_rate", "count_distinct", "sum", "avg", "min", "max", "p50"];

function cell(v: unknown): string {
  if (v === null || v === undefined) return "unknown";
  if (typeof v === "number") return Number.isInteger(v) ? v.toLocaleString() : v.toFixed(3);
  return String(v);
}

function useWorkspaceCollections(wid: string) {
  const projects = useQuery({
    queryKey: ["projects", wid],
    queryFn: () => apiFetch<{ items: Project[] }>(`/workspaces/${wid}/projects`),
  });
  const cols = useQueries({
    queries: (projects.data?.items ?? []).map((p) => ({
      queryKey: ["collections", wid, p.id],
      queryFn: () => apiFetch<{ items: Collection[] }>(`/projects/${p.id}/collections`),
    })),
  });
  const all = cols.flatMap((q, i) =>
    (q.data?.items ?? []).map((c) => ({ ...c, projectName: projects.data?.items[i]?.name ?? "" }))
  );
  return { collections: all, loading: projects.isLoading };
}

function AggregationExplorer({ wid }: { wid: string }) {
  const { collections } = useWorkspaceCollections(wid);
  const [cid, setCid] = useState("");
  const [groupBy, setGroupBy] = useState<string[]>([""]);
  const [metrics, setMetrics] = useState<AggregateMetric[]>([{ op: "count" }]);
  const [filterText, setFilterText] = useState("");
  const [limit, setLimit] = useState(50);
  const [histInterval, setHistInterval] = useState<"day" | "week" | "month">("day");
  const [filterError, setFilterError] = useState<string | null>(null);

  const fields = useQuery({
    queryKey: ["fields", cid],
    queryFn: () => apiFetch<FieldsResponse>(`/collections/${cid}/analytics/fields`),
    enabled: !!cid,
  });
  const groupable = useMemo(() => (fields.data?.fields ?? []).filter((f) => f.groupable), [fields.data]);
  const numeric = useMemo(
    () => (fields.data?.fields ?? []).filter((f) => f.queryable && f.types.number),
    [fields.data]
  );

  function parsedFilter(): Record<string, unknown> | null | undefined {
    if (!filterText.trim()) return null;
    try {
      setFilterError(null);
      return JSON.parse(filterText) as Record<string, unknown>;
    } catch {
      setFilterError("Filter must be valid JSON, e.g. {\"field\": \"has_website\", \"op\": \"eq\", \"value\": false}");
      return undefined;
    }
  }

  const run = useMutation({
    mutationFn: (filter: Record<string, unknown> | null) =>
      apiFetch<AggregateResponse>(`/collections/${cid}/analytics/aggregate`, {
        method: "POST",
        body: {
          group_by: groupBy.filter(Boolean),
          metrics: metrics.map((m) => (m.op === "count" && !m.field ? { op: "count" } : m)),
          filter,
          limit,
        },
      }),
  });
  const hist = useMutation({
    mutationFn: (filter: Record<string, unknown> | null) =>
      apiFetch<HistogramResponse>(`/collections/${cid}/analytics/histogram`, {
        method: "POST",
        body: { date_field: "created_at", interval: histInterval, filter },
      }),
  });
  const maxBucket = Math.max(1, ...(hist.data?.buckets ?? []).map((b) => b.count));

  return (
    <div className="space-y-4">
      <Card className="space-y-3">
        <h2 className="text-base font-semibold">Aggregation explorer</h2>
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          The same server-side engine MCP clients use (dc_aggregate), so numbers match what Claude or
          ChatGPT report. Missing values are shown as “unknown”, never as false.
        </p>
        <label className="block text-sm">
          <span className="mb-1 block text-xs font-medium">Collection</span>
          <Select value={cid} onChange={(e) => setCid(e.target.value)} className="w-full" aria-label="Collection">
            <option value="">Choose a collection…</option>
            {collections.map((c) => (
              <option key={c.id} value={c.id}>
                {c.projectName} / {c.slug}
              </option>
            ))}
          </Select>
        </label>
        {cid && fields.isLoading && <SkeletonTable rows={2} />}
        {cid && fields.data && (
          <>
            <p className="text-xs text-[hsl(var(--muted-foreground))]">
              {fields.data.total_records.toLocaleString()} records · fields sampled from{" "}
              {fields.data.sampled_records.toLocaleString()}
            </p>
            <div className="grid gap-3 md:grid-cols-3">
              {groupBy.map((g, i) => (
                <label key={i} className="text-sm">
                  <span className="mb-1 block text-xs font-medium">Group by {i + 1}</span>
                  <Select
                    className="w-full"
                    value={g}
                    aria-label={`Group by ${i + 1}`}
                    onChange={(e) => setGroupBy(groupBy.map((x, j) => (j === i ? e.target.value : x)))}
                  >
                    <option value="">(none)</option>
                    {groupable.map((f) => (
                      <option key={f.field} value={f.field}>
                        {f.field} · {Math.round(f.fill_rate * 100)}% filled
                      </option>
                    ))}
                  </Select>
                </label>
              ))}
              {groupBy.length < 3 && (
                <Button size="sm" variant="secondary" className="self-end" onClick={() => setGroupBy([...groupBy, ""])}>
                  Add group
                </Button>
              )}
            </div>
            <div className="space-y-2">
              {metrics.map((m, i) => (
                <div key={i} className="flex flex-wrap gap-2">
                  <Select
                    value={m.op}
                    aria-label={`Metric ${i + 1} operation`}
                    onChange={(e) =>
                      setMetrics(metrics.map((x, j) => (j === i ? { ...x, op: e.target.value as AggregateMetric["op"] } : x)))
                    }
                  >
                    {OPS.map((op) => (
                      <option key={op} value={op}>
                        {op}
                      </option>
                    ))}
                  </Select>
                  <Select
                    value={m.field ?? ""}
                    aria-label={`Metric ${i + 1} field`}
                    onChange={(e) =>
                      setMetrics(metrics.map((x, j) => (j === i ? { ...x, field: e.target.value || undefined } : x)))
                    }
                  >
                    <option value="">{m.op === "count" ? "(all records)" : "choose field"}</option>
                    {(["sum", "avg", "min", "max", "p50"].includes(m.op) ? numeric : groupable).map((f) => (
                      <option key={f.field} value={f.field}>
                        {f.field}
                      </option>
                    ))}
                  </Select>
                  {metrics.length > 1 && (
                    <Button size="sm" variant="ghost" onClick={() => setMetrics(metrics.filter((_, j) => j !== i))}>
                      Remove
                    </Button>
                  )}
                </div>
              ))}
              {metrics.length < 10 && (
                <Button size="sm" variant="secondary" onClick={() => setMetrics([...metrics, { op: "count" }])}>
                  Add metric
                </Button>
              )}
            </div>
            <label className="block text-sm">
              <span className="mb-1 block text-xs font-medium">Filter (optional, safe query DSL)</span>
              <textarea
                rows={2}
                value={filterText}
                onChange={(e) => setFilterText(e.target.value)}
                placeholder='{"field": "has_website", "op": "eq", "value": false}'
                className="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-2 font-mono text-xs"
              />
            </label>
            {filterError && <p className="text-xs text-[hsl(var(--destructive))]">{filterError}</p>}
            <div className="flex flex-wrap items-end gap-2">
              <label className="text-sm">
                <span className="mb-1 block text-xs font-medium">Max groups</span>
                <Input
                  type="number"
                  min={1}
                  max={500}
                  value={limit}
                  onChange={(e) => setLimit(Math.min(500, Math.max(1, Number(e.target.value) || 1)))}
                  className="w-24"
                />
              </label>
              <Button
                onClick={() => {
                  const f = parsedFilter();
                  if (f !== undefined) run.mutate(f);
                }}
                disabled={run.isPending}
              >
                {run.isPending ? "Running…" : "Run aggregation"}
              </Button>
            </div>
          </>
        )}
      </Card>

      {run.isError && <ErrorState error={run.error} />}
      {run.data && (
        <Card className="space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Badge tone="primary">{run.data.coverage.matched.toLocaleString()} matched</Badge>
            {Object.entries(run.data.coverage.unknown).map(([f, n]) => (
              <Badge key={f} tone={n ? "warning" : "neutral"}>
                {f}: {n.toLocaleString()} unknown
              </Badge>
            ))}
            {run.data.truncated && <Badge tone="warning">more groups exist</Badge>}
            <span className="text-xs text-[hsl(var(--muted-foreground))]">
              data from {cell(run.data.coverage.freshness.min_created_at)} to{" "}
              {cell(run.data.coverage.freshness.max_created_at)}
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm" aria-label="Aggregation results">
              <thead className="text-left text-xs text-[hsl(var(--muted-foreground))]">
                <tr>
                  {run.data.group_by.map((g) => (
                    <th key={g} className="py-1 pr-3">
                      {g}
                    </th>
                  ))}
                  {run.data.metrics.map((m) => (
                    <th key={m.as} className="py-1 pr-3 text-right">
                      {m.as}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {run.data.rows.map((r, i) => (
                  <tr key={i} className="border-t border-[hsl(var(--border))]">
                    {run.data.group_by.map((g) => (
                      <td key={g} className={`py-1 pr-3 ${r.group?.[g] == null ? "italic text-[hsl(var(--muted-foreground))]" : ""}`}>
                        {cell(r.group?.[g])}
                      </td>
                    ))}
                    {run.data.metrics.map((m) => (
                      <td key={m.as} className="py-1 pr-3 text-right tabular-nums">
                        {cell(r[m.as])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {cid && (
        <Card className="space-y-3">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <h2 className="text-base font-semibold">Records added over time</h2>
            <div className="flex items-end gap-2">
              <Select value={histInterval} aria-label="Interval" onChange={(e) => setHistInterval(e.target.value as typeof histInterval)}>
                <option value="day">per day</option>
                <option value="week">per week</option>
                <option value="month">per month</option>
              </Select>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  const f = parsedFilter();
                  if (f !== undefined) hist.mutate(f);
                }}
                disabled={hist.isPending}
              >
                Show
              </Button>
            </div>
          </div>
          {hist.isError && <ErrorState error={hist.error} />}
          {hist.data && (
            <ul className="space-y-1" aria-label="Histogram">
              {hist.data.buckets.map((b) => (
                <li key={b.bucket} className="flex items-center gap-2 text-xs">
                  <span className="w-24 shrink-0 font-mono">{b.bucket}</span>
                  <span
                    className="h-3 rounded bg-[hsl(var(--primary))]"
                    style={{ width: `${Math.max(2, (b.count / maxBucket) * 100)}%` }}
                    aria-hidden="true"
                  />
                  <span className="tabular-nums">{b.count.toLocaleString()}</span>
                </li>
              ))}
              {hist.data.buckets.length === 0 && <li className="text-sm">No records.</li>}
            </ul>
          )}
        </Card>
      )}
    </div>
  );
}

export default function UsageAnalyticsPage() {
  const { workspaceId: wid } = useParams<{ workspaceId: string }>();

  const usageQuery = useQuery({
    queryKey: ["usage", wid],
    queryFn: () => apiFetch<UsageSummary>(`/workspaces/${wid}/usage`),
  });

  return (
    <AppShell workspaceId={wid}>
      <PageHeader title="Usage & Analytics" subtitle="Workspace counters and server-side aggregations" />
      {usageQuery.isLoading && <SkeletonTable rows={3} />}
      {usageQuery.isError && <ErrorState error={usageQuery.error} />}
      {usageQuery.data && (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <StatCard label="Active Records" value={usageQuery.data.records_active} />
            <StatCard label="Collections" value={usageQuery.data.collections} />
            <StatCard label="Completed Jobs" value={usageQuery.data.jobs_completed} />
            <StatCard label="Failed Jobs" value={usageQuery.data.jobs_failed} />
            <StatCard label="Audit Events" value={usageQuery.data.audit_events} />
          </div>
          <AggregationExplorer wid={wid} />
        </div>
      )}
    </AppShell>
  );
}
