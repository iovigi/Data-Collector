"use client";

import React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import type { DashboardSummary, WorkspaceCapabilities } from "@/lib/api/types";
import { AppShell } from "@/components/layout/AppShell";
import {
  Badge,
  Button,
  Card,
  ErrorState,
  PageHeader,
  SkeletonTable,
  StatCard,
} from "@/components/ui/primitives";

export default function WorkspaceOverviewPage() {
  const params = useParams<{ workspaceId: string }>();
  const wid = params.workspaceId;

  const summaryQuery = useQuery({
    queryKey: ["dashboard-summary", wid],
    queryFn: () => apiFetch<DashboardSummary>(`/workspaces/${wid}/dashboard/summary`),
  });

  const capsQuery = useQuery({
    queryKey: ["capabilities", wid],
    queryFn: () => apiFetch<WorkspaceCapabilities>(`/workspaces/${wid}/capabilities`),
  });

  const caps = capsQuery.data?.features;

  return (
    <AppShell workspaceId={wid}>
      <PageHeader
        title="Workspace Overview"
        subtitle="Live operational counters and recent tenant activity"
        actions={
          <>
            {caps?.can_manage_collections && (
              <Link href={`/w/${wid}/projects`}>
                <Button size="sm">New Project</Button>
              </Link>
            )}
            {caps?.can_create_keys && (
              <Link href={`/w/${wid}/keys`}>
                <Button size="sm" variant="secondary">
                  Manage API Keys
                </Button>
              </Link>
            )}
          </>
        }
      />

      {summaryQuery.isLoading && <SkeletonTable rows={4} />}
      {summaryQuery.isError && (
        <ErrorState error={summaryQuery.error} onRetry={() => summaryQuery.refetch()} />
      )}

      {summaryQuery.data && (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <StatCard label="Active Records" value={summaryQuery.data.counts.records_active} />
            <StatCard label="Projects" value={summaryQuery.data.counts.projects} />
            <StatCard label="Collections" value={summaryQuery.data.counts.collections} />
            <StatCard label="Completed Jobs" value={summaryQuery.data.counts.jobs_completed} />
            <StatCard
              label="Audit Events"
              value={summaryQuery.data.counts.audit_events ?? "Restricted"}
            />
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-base font-semibold">Recent Projects</h2>
                <Link href={`/w/${wid}/projects`} className="text-xs text-[hsl(var(--primary))] hover:underline">
                  View all
                </Link>
              </div>
              {summaryQuery.data.recent_projects.length === 0 ? (
                <p className="text-sm text-[hsl(var(--muted-foreground))]">No projects yet.</p>
              ) : (
                <ul className="divide-y divide-[hsl(var(--border))]">
                  {summaryQuery.data.recent_projects.map((p) => (
                    <li key={p.id} className="flex items-center justify-between py-2.5 text-sm">
                      <Link href={`/w/${wid}/projects/${p.id}`} className="font-medium hover:underline">
                        {p.name}
                      </Link>
                      <Badge tone={p.status === "active" ? "success" : "warning"}>{p.status}</Badge>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card>
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-base font-semibold">Recent Jobs</h2>
                <Link href={`/w/${wid}/jobs`} className="text-xs text-[hsl(var(--primary))] hover:underline">
                  View all
                </Link>
              </div>
              {summaryQuery.data.recent_jobs.length === 0 ? (
                <p className="text-sm text-[hsl(var(--muted-foreground))]">No background jobs recorded.</p>
              ) : (
                <ul className="divide-y divide-[hsl(var(--border))]">
                  {summaryQuery.data.recent_jobs.map((j) => (
                    <li key={j.id} className="flex items-center justify-between py-2.5 text-sm">
                      <span className="font-mono text-xs">{j.type.toUpperCase()} · {j.id.slice(-8)}</span>
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
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </div>
      )}
    </AppShell>
  );
}
