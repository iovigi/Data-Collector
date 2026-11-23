import React, { useState } from "react";
import { Link } from "@/lib/router";
import { useParams } from "@/lib/router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import type { Collection, Project, WorkspaceCapabilities } from "@/lib/api/types";
import { AppShell } from "@/components/layout/AppShell";
import { useToast } from "@/components/providers";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Input,
  Modal,
  PageHeader,
  SkeletonTable,
} from "@/components/ui/primitives";

export default function ProjectDetailPage() {
  const { workspaceId: wid, projectId: pid } = useParams<{
    workspaceId: string;
    projectId: string;
  }>();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [openCol, setOpenCol] = useState(false);
  const [colSlug, setColSlug] = useState("");
  const [schemaText, setSchemaText] = useState(
    JSON.stringify(
      {
        type: "object",
        required: ["name"],
        properties: {
          name: { type: "string" },
          status: { type: "string" },
          score: { type: "number" },
        },
      },
      null,
      2
    )
  );
  const [searchable, setSearchable] = useState("name,status,score");

  const projectQuery = useQuery({
    queryKey: ["project", wid, pid],
    queryFn: () => apiFetch<Project>(`/projects/${pid}`),
  });

  const colsQuery = useQuery({
    queryKey: ["collections", wid, pid],
    queryFn: () => apiFetch<{ items: Collection[] }>(`/projects/${pid}/collections`),
  });

  const capsQuery = useQuery({
    queryKey: ["capabilities", wid],
    queryFn: () => apiFetch<WorkspaceCapabilities>(`/workspaces/${wid}/capabilities`),
  });

  const archiveMutation = useMutation({
    mutationFn: (action: "archive" | "restore") =>
      apiFetch<Project>(`/projects/${pid}/${action}`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project", wid, pid] });
      toast({ title: "Project status updated", variant: "success" });
    },
  });

  const createColMutation = useMutation({
    mutationFn: () => {
      const parsedSchema = JSON.parse(schemaText) as Record<string, unknown>;
      const fields = searchable
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      return apiFetch<Collection>(`/projects/${pid}/collections`, {
        method: "POST",
        body: {
          slug: colSlug.trim(),
          schema_json: parsedSchema,
          searchable_fields: fields,
        },
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["collections", wid, pid] });
      setOpenCol(false);
      setColSlug("");
      toast({ title: "Collection created", variant: "success" });
    },
    onError: (err: Error) =>
      toast({ title: "Failed to create collection", description: err.message, variant: "error" }),
  });

  const canManage = capsQuery.data?.features.can_manage_collections ?? false;

  return (
    <AppShell workspaceId={wid}>
      {projectQuery.isError && <ErrorState error={projectQuery.error} />}
      {projectQuery.data && (
        <PageHeader
          title={projectQuery.data.name}
          subtitle={`Project slug: ${projectQuery.data.slug}`}
          actions={
            canManage && (
              <>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() =>
                    archiveMutation.mutate(
                      projectQuery.data.status === "active" ? "archive" : "restore"
                    )
                  }
                >
                  {projectQuery.data.status === "active" ? "Archive Project" : "Restore Project"}
                </Button>
                <Button size="sm" onClick={() => setOpenCol(true)}>
                  New Collection
                </Button>
              </>
            )
          }
        />
      )}

      {colsQuery.isLoading && <SkeletonTable rows={4} />}
      {colsQuery.isError && <ErrorState error={colsQuery.error} />}
      {colsQuery.data && colsQuery.data.items.length === 0 && (
        <EmptyState
          title="No collections in this project"
          description="Create a collection with a JSON Schema to begin storing validated records."
        />
      )}

      {colsQuery.data && colsQuery.data.items.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {colsQuery.data.items.map((col) => (
            <Card key={col.id}>
              <div className="flex items-center justify-between">
                <div className="font-semibold">{col.slug}</div>
                <Badge tone="primary">v{col.schema_version}</Badge>
              </div>
              <div className="mt-2 text-xs text-[hsl(var(--muted-foreground))]">
                Searchable: {col.searchable_fields.join(", ") || "default"}
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <Link href={`/w/${wid}/collections/${col.id}/data`}>
                  <Button size="sm">Data Explorer</Button>
                </Link>
                <Link href={`/w/${wid}/collections/${col.id}/schema`}>
                  <Button size="sm" variant="secondary">
                    Schema
                  </Button>
                </Link>
                <Link href={`/w/${wid}/collections/${col.id}/queries`}>
                  <Button size="sm" variant="secondary">
                    Queries
                  </Button>
                </Link>
              </div>
            </Card>
          ))}
        </div>
      )}

      <Modal open={openCol} onClose={() => setOpenCol(false)} title="Create Collection">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            createColMutation.mutate();
          }}
          className="space-y-4"
        >
          <div>
            <label htmlFor="col-slug" className="mb-1 block text-sm font-medium">
              Collection Slug
            </label>
            <Input
              id="col-slug"
              required
              minLength={3}
              value={colSlug}
              onChange={(e) => setColSlug(e.target.value.toLowerCase())}
              placeholder="leads"
            />
          </div>
          <div>
            <label htmlFor="col-search" className="mb-1 block text-sm font-medium">
              Searchable Fields (comma-separated)
            </label>
            <Input
              id="col-search"
              value={searchable}
              onChange={(e) => setSearchable(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="col-schema" className="mb-1 block text-sm font-medium">
              JSON Schema (2020-12)
            </label>
            <textarea
              id="col-schema"
              rows={8}
              value={schemaText}
              onChange={(e) => setSchemaText(e.target.value)}
              className="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-2.5 font-mono text-xs"
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setOpenCol(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={createColMutation.isPending}>
              {createColMutation.isPending ? "Creating..." : "Create"}
            </Button>
          </div>
        </form>
      </Modal>
    </AppShell>
  );
}
