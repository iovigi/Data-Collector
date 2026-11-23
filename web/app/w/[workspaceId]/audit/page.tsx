import React, { useState } from "react";
import { useParams } from "@/lib/router";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import type { AuditEvent, WorkspaceCapabilities } from "@/lib/api/types";
import { AppShell } from "@/components/layout/AppShell";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Input,
  PageHeader,
  PermissionDenied,
  Select,
  SkeletonTable,
} from "@/components/ui/primitives";

export default function AuditLogPage() {
  const { workspaceId: wid } = useParams<{ workspaceId: string }>();
  const [actionFilter, setActionFilter] = useState("");
  const [decisionFilter, setDecisionFilter] = useState("");
  const [cursorStack, setCursorStack] = useState<Array<string | null>>([null]);
  const cursor = cursorStack[cursorStack.length - 1] ?? null;

  const capsQuery = useQuery({
    queryKey: ["capabilities", wid],
    queryFn: () => apiFetch<WorkspaceCapabilities>(`/workspaces/${wid}/capabilities`),
  });
  const canReadAudit = capsQuery.data?.features.can_read_audit ?? false;

  const auditQuery = useQuery({
    queryKey: ["audit", wid, actionFilter, decisionFilter, cursor],
    queryFn: () => {
      const qs = new URLSearchParams({ limit: "25" });
      if (actionFilter.trim()) qs.set("action", actionFilter.trim());
      if (decisionFilter) qs.set("decision", decisionFilter);
      if (cursor) qs.set("cursor", cursor);
      return apiFetch<{ items: AuditEvent[]; next_cursor: string | null; has_more: boolean }>(
        `/workspaces/${wid}/audit?${qs.toString()}`
      );
    },
    enabled: canReadAudit,
  });

  return (
    <AppShell workspaceId={wid}>
      <PageHeader
        title="Audit Log"
        subtitle="Immutable, secret-scrubbed security and mutation events"
        actions={
          canReadAudit && (
            <div className="flex gap-2">
              <Input
                aria-label="Filter by action"
                placeholder="Action (e.g. record.create)"
                value={actionFilter}
                onChange={(e) => {
                  setActionFilter(e.target.value);
                  setCursorStack([null]);
                }}
                className="w-48"
              />
              <Select
                aria-label="Filter by decision"
                value={decisionFilter}
                onChange={(e) => {
                  setDecisionFilter(e.target.value);
                  setCursorStack([null]);
                }}
              >
                <option value="">All decisions</option>
                <option value="allow">Allow</option>
                <option value="deny">Deny</option>
              </Select>
            </div>
          )
        }
      />

      {capsQuery.isLoading && <SkeletonTable rows={4} />}
      {capsQuery.data && !canReadAudit && (
        <PermissionDenied message="Your role does not include audit:read permission." />
      )}
      {canReadAudit && auditQuery.isLoading && <SkeletonTable rows={5} />}
      {canReadAudit && auditQuery.isError && <ErrorState error={auditQuery.error} />}
      {canReadAudit && auditQuery.data && auditQuery.data.items.length === 0 && (
        <EmptyState title="No audit events" description="No events match your current filters." />
      )}

      {canReadAudit && auditQuery.data && auditQuery.data.items.length > 0 && (
        <>
          <Card className="overflow-x-auto p-0">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-[hsl(var(--border))] bg-[hsl(var(--surface))] text-xs uppercase text-[hsl(var(--muted-foreground))]">
                <tr>
                  <th className="px-4 py-3">Timestamp</th>
                  <th className="px-4 py-3">Actor</th>
                  <th className="px-4 py-3">Action</th>
                  <th className="px-4 py-3">Target</th>
                  <th className="px-4 py-3">Decision</th>
                  <th className="px-4 py-3">Request ID</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[hsl(var(--border))]">
                {auditQuery.data.items.map((ev) => (
                  <tr key={ev.id}>
                    <td className="px-4 py-2.5 text-xs">{ev.timestamp}</td>
                    <td className="px-4 py-2.5 font-mono text-xs">{ev.actor}</td>
                    <td className="px-4 py-2.5 font-mono text-xs">{ev.action}</td>
                    <td className="px-4 py-2.5 font-mono text-xs">{ev.target}</td>
                    <td className="px-4 py-2.5">
                      <Badge tone={ev.decision === "allow" ? "success" : "danger"}>
                        {ev.decision}
                      </Badge>
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs">{ev.request_id ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          <div className="mt-4 flex justify-end gap-2">
            <Button
              size="sm"
              variant="secondary"
              disabled={cursorStack.length <= 1}
              onClick={() => setCursorStack((s) => s.slice(0, -1))}
            >
              Previous
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={!auditQuery.data.has_more || !auditQuery.data.next_cursor}
              onClick={() => setCursorStack((s) => [...s, auditQuery.data!.next_cursor])}
            >
              Next
            </Button>
          </div>
        </>
      )}
    </AppShell>
  );
}
