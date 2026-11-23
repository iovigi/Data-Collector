import React, { useState } from "react";
import { useParams } from "@/lib/router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import type { JobItem, WorkspaceCapabilities } from "@/lib/api/types";
import { AppShell } from "@/components/layout/AppShell";
import { useToast } from "@/components/providers";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  PageHeader,
  Select,
  SkeletonTable,
} from "@/components/ui/primitives";

export default function JobsPage() {
  const { workspaceId: wid } = useParams<{ workspaceId: string }>();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [stateFilter, setStateFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");

  const jobsQuery = useQuery({
    queryKey: ["jobs", wid, stateFilter, typeFilter],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (stateFilter) qs.set("state", stateFilter);
      if (typeFilter) qs.set("type", typeFilter);
      return apiFetch<{ items: JobItem[]; has_more: boolean }>(
        `/workspaces/${wid}/jobs?${qs.toString()}`
      );
    },
    refetchInterval: (q) => {
      const items = q.state.data?.items ?? [];
      return items.some((j) => j.state === "queued" || j.state === "running") ? 3000 : false;
    },
  });

  const capsQuery = useQuery({
    queryKey: ["capabilities", wid],
    queryFn: () => apiFetch<WorkspaceCapabilities>(`/workspaces/${wid}/capabilities`),
  });

  const cancelMutation = useMutation({
    mutationFn: (jid: string) => apiFetch<JobItem>(`/jobs/${jid}/cancel`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs", wid] });
      toast({ title: "Job cancelled", variant: "success" });
    },
  });

  const canCreate = capsQuery.data?.features.can_create_jobs ?? false;

  return (
    <AppShell workspaceId={wid}>
      <PageHeader
        title="Imports, Exports & Jobs"
        subtitle="Track background worker execution, row validation errors, and export downloads"
        actions={
          <div className="flex gap-2">
            <Select
              aria-label="Filter by job type"
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
            >
              <option value="">All types</option>
              <option value="import">Import</option>
              <option value="export">Export</option>
            </Select>
            <Select
              aria-label="Filter by job state"
              value={stateFilter}
              onChange={(e) => setStateFilter(e.target.value)}
            >
              <option value="">All states</option>
              <option value="queued">Queued</option>
              <option value="running">Running</option>
              <option value="completed">Completed</option>
              <option value="failed">Failed</option>
              <option value="cancelled">Cancelled</option>
            </Select>
          </div>
        }
      />

      {jobsQuery.isLoading && <SkeletonTable rows={5} />}
      {jobsQuery.isError && <ErrorState error={jobsQuery.error} />}
      {jobsQuery.data && jobsQuery.data.items.length === 0 && (
        <EmptyState
          title="No jobs found"
          description="Run an import or export from Data Explorer to see background jobs here."
        />
      )}

      {jobsQuery.data && jobsQuery.data.items.length > 0 && (
        <Card className="overflow-x-auto p-0">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-[hsl(var(--border))] bg-[hsl(var(--surface))] text-xs uppercase text-[hsl(var(--muted-foreground))]">
              <tr>
                <th className="px-4 py-3">Job ID</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">State</th>
                <th className="px-4 py-3">Progress</th>
                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[hsl(var(--border))]">
              {jobsQuery.data.items.map((j) => (
                <tr key={j.id}>
                  <td className="px-4 py-2.5 font-mono text-xs">{j.id}</td>
                  <td className="px-4 py-2.5 uppercase">{j.type}</td>
                  <td className="px-4 py-2.5">
                    <Badge
                      tone={
                        j.state === "completed"
                          ? "success"
                          : j.state === "failed"
                            ? "danger"
                            : "primary"
                      }
                    >
                      {j.state}
                    </Badge>
                  </td>
                  <td className="px-4 py-2.5 text-xs">
                    {j.progress.succeeded} ok / {j.progress.failed} failed
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex gap-2">
                      {j.type === "export" && j.state === "completed" && (
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() =>
                            window.open(`/api/backend/jobs/${j.id}/result`, "_blank", "noopener")
                          }
                        >
                          Download
                        </Button>
                      )}
                      {canCreate && (j.state === "queued" || j.state === "running") && (
                        <Button
                          size="sm"
                          variant="danger"
                          onClick={() => cancelMutation.mutate(j.id)}
                        >
                          Cancel
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </AppShell>
  );
}
