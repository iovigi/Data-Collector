"use client";

import React, { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import type { Collection, WorkspaceCapabilities } from "@/lib/api/types";
import { AppShell } from "@/components/layout/AppShell";
import { useToast } from "@/components/providers";
import { Badge, Button, Card, ErrorState, PageHeader, SkeletonTable } from "@/components/ui/primitives";

interface MigrationPreview {
  collection_id: string;
  current_version: number;
  checked_records: number;
  failing_records: number;
  compatible: boolean;
  failures: Array<{ record_id: string; reason: string }>;
}

export default function CollectionSchemaPage() {
  const { workspaceId: wid, collectionId: cid } = useParams<{
    workspaceId: string;
    collectionId: string;
  }>();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [schemaText, setSchemaText] = useState("");
  const [preview, setPreview] = useState<MigrationPreview | null>(null);

  const colQuery = useQuery({
    queryKey: ["collection", wid, cid],
    queryFn: () => apiFetch<Collection>(`/collections/${cid}`),
  });

  const capsQuery = useQuery({
    queryKey: ["capabilities", wid],
    queryFn: () => apiFetch<WorkspaceCapabilities>(`/workspaces/${wid}/capabilities`),
  });

  useEffect(() => {
    if (colQuery.data) {
      setSchemaText(JSON.stringify(colQuery.data.schema_json, null, 2));
    }
  }, [colQuery.data]);

  const previewMutation = useMutation({
    mutationFn: () =>
      apiFetch<MigrationPreview>(`/collections/${cid}/schema-migrations/preview`, {
        method: "POST",
        body: { schema_json: JSON.parse(schemaText) },
      }),
    onSuccess: (res) => setPreview(res),
    onError: (err: Error) =>
      toast({ title: "Preview failed", description: err.message, variant: "error" }),
  });

  const applyMutation = useMutation({
    mutationFn: () =>
      apiFetch<Collection>(`/collections/${cid}/schema-migrations/apply`, {
        method: "POST",
        body: { schema_json: JSON.parse(schemaText) },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["collection", wid, cid] });
      setPreview(null);
      toast({ title: "Schema migration applied", variant: "success" });
    },
    onError: (err: Error) =>
      toast({ title: "Migration blocked", description: err.message, variant: "error" }),
  });

  const canManage = capsQuery.data?.features.can_manage_collections ?? false;

  return (
    <AppShell workspaceId={wid}>
      <PageHeader
        title={`Schema · ${colQuery.data?.slug ?? ""}`}
        subtitle={`Current version: v${colQuery.data?.schema_version ?? 1}`}
      />
      {colQuery.isLoading && <SkeletonTable rows={5} />}
      {colQuery.isError && <ErrorState error={colQuery.error} />}
      {colQuery.data && (
        <div className="space-y-4">
          <Card>
            <label htmlFor="schema-editor" className="mb-2 block text-sm font-medium">
              JSON Schema 2020-12
            </label>
            <textarea
              id="schema-editor"
              rows={16}
              readOnly={!canManage}
              value={schemaText}
              onChange={(e) => setSchemaText(e.target.value)}
              className="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3 font-mono text-xs"
            />
            {canManage && (
              <div className="mt-4 flex gap-2">
                <Button
                  variant="secondary"
                  onClick={() => previewMutation.mutate()}
                  disabled={previewMutation.isPending}
                >
                  Preview Migration Impact
                </Button>
                <Button
                  onClick={() => applyMutation.mutate()}
                  disabled={applyMutation.isPending || (preview !== null && !preview.compatible)}
                >
                  Apply Schema Migration
                </Button>
              </div>
            )}
          </Card>

          {preview && (
            <Card>
              <div className="flex items-center gap-2">
                <span className="font-semibold">Migration Preview</span>
                <Badge tone={preview.compatible ? "success" : "danger"}>
                  {preview.compatible ? "Compatible" : `${preview.failing_records} failing`}
                </Badge>
              </div>
              <p className="mt-1 text-xs text-[hsl(var(--muted-foreground))]">
                Checked {preview.checked_records} existing records.
              </p>
              {preview.failures.length > 0 && (
                <pre className="mt-3 max-h-40 overflow-auto rounded bg-[hsl(var(--background))] p-2 font-mono text-xs">
                  {JSON.stringify(preview.failures, null, 2)}
                </pre>
              )}
            </Card>
          )}
        </div>
      )}
    </AppShell>
  );
}
