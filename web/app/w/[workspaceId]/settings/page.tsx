import React, { useEffect, useState } from "react";
import { useParams } from "@/lib/router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import type { Workspace, WorkspaceCapabilities } from "@/lib/api/types";
import { AppShell } from "@/components/layout/AppShell";
import { useToast } from "@/components/providers";
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  ErrorState,
  Input,
  PageHeader,
  SkeletonTable,
} from "@/components/ui/primitives";

export default function WorkspaceSettingsPage() {
  const { workspaceId: wid } = useParams<{ workspaceId: string }>();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [name, setName] = useState("");
  const [confirmArchive, setConfirmArchive] = useState(false);

  const wsQuery = useQuery({
    queryKey: ["workspace", wid],
    queryFn: () => apiFetch<Workspace>(`/workspaces/${wid}`),
  });

  const capsQuery = useQuery({
    queryKey: ["capabilities", wid],
    queryFn: () => apiFetch<WorkspaceCapabilities>(`/workspaces/${wid}/capabilities`),
  });

  useEffect(() => {
    if (wsQuery.data) setName(wsQuery.data.name);
  }, [wsQuery.data]);

  const renameMutation = useMutation({
    mutationFn: () =>
      apiFetch<Workspace>(`/workspaces/${wid}`, { method: "PATCH", body: { name } }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workspace", wid] });
      queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      toast({ title: "Workspace updated", variant: "success" });
    },
    onError: (err: Error) =>
      toast({ title: "Update failed", description: err.message, variant: "error" }),
  });

  const lifecycleMutation = useMutation({
    mutationFn: (action: "archive" | "restore") =>
      apiFetch<Workspace>(`/workspaces/${wid}/${action}`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workspace", wid] });
      setConfirmArchive(false);
      toast({ title: "Workspace status updated", variant: "success" });
    },
  });

  const canManage = capsQuery.data?.features.can_manage_workspace ?? false;

  return (
    <AppShell workspaceId={wid}>
      <PageHeader title="Workspace Settings" subtitle="Profile and workspace lifecycle controls" />
      {wsQuery.isLoading && <SkeletonTable rows={3} />}
      {wsQuery.isError && <ErrorState error={wsQuery.error} />}
      {wsQuery.data && (
        <div className="space-y-6">
          <Card>
            <div className="mb-4 flex items-center gap-2">
              <h2 className="text-base font-semibold">Profile</h2>
              <Badge tone={wsQuery.data.status === "active" ? "success" : "warning"}>
                {wsQuery.data.status}
              </Badge>
            </div>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                renameMutation.mutate();
              }}
              className="max-w-md space-y-4"
            >
              <div>
                <label htmlFor="ws-set-name" className="mb-1 block text-sm font-medium">
                  Workspace Name
                </label>
                <Input
                  id="ws-set-name"
                  readOnly={!canManage}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>
              <div>
                <div className="text-xs text-[hsl(var(--muted-foreground))]">
                  Slug: <code>{wsQuery.data.slug}</code>
                </div>
              </div>
              {canManage && (
                <Button type="submit" disabled={renameMutation.isPending}>
                  Save Name
                </Button>
              )}
            </form>
          </Card>

          {canManage && (
            <Card className="border-l-4 border-l-[hsl(var(--destructive))]">
              <h2 className="text-base font-semibold text-[hsl(var(--destructive))]">
                Lifecycle Controls
              </h2>
              <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
                Archiving marks this workspace inactive without deleting records.
              </p>
              <div className="mt-4">
                {wsQuery.data.status === "active" ? (
                  <Button variant="danger" onClick={() => setConfirmArchive(true)}>
                    Archive Workspace
                  </Button>
                ) : (
                  <Button variant="secondary" onClick={() => lifecycleMutation.mutate("restore")}>
                    Restore Workspace
                  </Button>
                )}
              </div>
            </Card>
          )}
        </div>
      )}

      <ConfirmDialog
        open={confirmArchive}
        onClose={() => setConfirmArchive(false)}
        onConfirm={() => lifecycleMutation.mutate("archive")}
        title="Archive Workspace"
        description="Are you sure you want to archive this workspace?"
        confirmLabel="Archive"
        danger
        loading={lifecycleMutation.isPending}
      />
    </AppShell>
  );
}
