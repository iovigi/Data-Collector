"use client";

import React, { useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import type { SavedQuery, SearchRecordsResponse, WorkspaceCapabilities } from "@/lib/api/types";
import { AppShell } from "@/components/layout/AppShell";
import { useToast } from "@/components/providers";
import { Button, Card, EmptyState, ErrorState, Input, PageHeader, SkeletonTable } from "@/components/ui/primitives";

export default function SavedQueriesPage() {
  const { workspaceId: wid, collectionId: cid } = useParams<{
    workspaceId: string;
    collectionId: string;
  }>();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [runResult, setRunResult] = useState<SearchRecordsResponse | null>(null);
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameVal, setRenameVal] = useState("");

  const listQuery = useQuery({
    queryKey: ["saved-queries", wid, cid],
    queryFn: () => apiFetch<{ items: SavedQuery[] }>(`/collections/${cid}/saved-queries`),
  });

  const capsQuery = useQuery({
    queryKey: ["capabilities", wid],
    queryFn: () => apiFetch<WorkspaceCapabilities>(`/workspaces/${wid}/capabilities`),
  });

  const runMutation = useMutation({
    mutationFn: (sqid: string) =>
      apiFetch<SearchRecordsResponse>(`/saved-queries/${sqid}/run`, { method: "POST" }),
    onSuccess: (res) => setRunResult(res),
    onError: (err: Error) => toast({ title: "Run failed", description: err.message, variant: "error" }),
  });

  const renameMutation = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      apiFetch<SavedQuery>(`/saved-queries/${id}`, { method: "PATCH", body: { name } }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["saved-queries", wid, cid] });
      setRenameId(null);
      toast({ title: "Saved query renamed", variant: "success" });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiFetch(`/saved-queries/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["saved-queries", wid, cid] });
      toast({ title: "Saved query deleted", variant: "success" });
    },
  });

  const canManage = capsQuery.data?.features.can_manage_collections ?? false;

  return (
    <AppShell workspaceId={wid}>
      <PageHeader title="Saved Queries" subtitle="Reusable Safe Query DSL definitions" />
      {listQuery.isLoading && <SkeletonTable rows={4} />}
      {listQuery.isError && <ErrorState error={listQuery.error} />}
      {listQuery.data && listQuery.data.items.length === 0 && (
        <EmptyState
          title="No saved queries"
          description="Save a filter from Data Explorer to reuse it here."
        />
      )}
      {listQuery.data && listQuery.data.items.length > 0 && (
        <div className="space-y-3">
          {listQuery.data.items.map((sq) => (
            <Card key={sq.id} className="flex flex-wrap items-center justify-between gap-3">
              <div>
                {renameId === sq.id ? (
                  <div className="flex items-center gap-2">
                    <Input value={renameVal} onChange={(e) => setRenameVal(e.target.value)} />
                    <Button
                      size="sm"
                      onClick={() => renameMutation.mutate({ id: sq.id, name: renameVal })}
                    >
                      Save
                    </Button>
                  </div>
                ) : (
                  <div className="font-semibold">{sq.name}</div>
                )}
                <div className="mt-1 font-mono text-xs text-[hsl(var(--muted-foreground))]">
                  {JSON.stringify(sq.filter ?? {})}
                </div>
              </div>
              <div className="flex gap-2">
                <Button size="sm" onClick={() => runMutation.mutate(sq.id)}>
                  Run
                </Button>
                {canManage && (
                  <>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => {
                        setRenameId(sq.id);
                        setRenameVal(sq.name);
                      }}
                    >
                      Rename
                    </Button>
                    <Button
                      size="sm"
                      variant="danger"
                      onClick={() => deleteMutation.mutate(sq.id)}
                    >
                      Delete
                    </Button>
                  </>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      {runResult && (
        <Card className="mt-6">
          <h2 className="mb-2 text-sm font-semibold">Query Results ({runResult.items.length})</h2>
          <pre className="max-h-72 overflow-auto rounded bg-[hsl(var(--background))] p-3 font-mono text-xs">
            {JSON.stringify(runResult.items, null, 2)}
          </pre>
        </Card>
      )}
    </AppShell>
  );
}
