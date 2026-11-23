import React from "react";
import { useParams } from "@/lib/router";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import { AppShell } from "@/components/layout/AppShell";
import { Card, ErrorState, PageHeader, SkeletonTable, StatCard } from "@/components/ui/primitives";

interface UsageSummary {
  workspace_id: string;
  records_active: number;
  collections: number;
  jobs_completed: number;
  jobs_failed: number;
  audit_events: number;
}

export default function UsageAnalyticsPage() {
  const { workspaceId: wid } = useParams<{ workspaceId: string }>();

  const usageQuery = useQuery({
    queryKey: ["usage", wid],
    queryFn: () => apiFetch<UsageSummary>(`/workspaces/${wid}/usage`),
  });

  return (
    <AppShell workspaceId={wid}>
      <PageHeader
        title="Usage & Analytics"
        subtitle="Measured workspace resource counters"
      />
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
          <Card>
            <h2 className="text-sm font-semibold">Historical Time-Series</h2>
            <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
              Historical daily trend charts are not displayed because no synthetic time-series are
              fabricated from point-in-time counters.
            </p>
          </Card>
        </div>
      )}
    </AppShell>
  );
}
