import React, { useState } from "react";
import { Link } from "@/lib/router";
import { useParams } from "@/lib/router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import type { Project, WorkspaceCapabilities } from "@/lib/api/types";
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

export default function ProjectsPage() {
  const { workspaceId: wid } = useParams<{ workspaceId: string }>();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [openCreate, setOpenCreate] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");

  const projectsQuery = useQuery({
    queryKey: ["projects", wid],
    queryFn: () => apiFetch<{ items: Project[] }>(`/workspaces/${wid}/projects`),
  });

  const capsQuery = useQuery({
    queryKey: ["capabilities", wid],
    queryFn: () => apiFetch<WorkspaceCapabilities>(`/workspaces/${wid}/capabilities`),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      apiFetch<Project>(`/workspaces/${wid}/projects`, {
        method: "POST",
        body: { name: name.trim(), slug: slug.trim() },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects", wid] });
      setOpenCreate(false);
      setName("");
      setSlug("");
      toast({ title: "Project created", variant: "success" });
    },
    onError: (err: Error) => toast({ title: "Failed to create project", description: err.message, variant: "error" }),
  });

  const canManage = capsQuery.data?.features.can_manage_collections ?? false;

  return (
    <AppShell workspaceId={wid}>
      <PageHeader
        title="Projects"
        subtitle="Organize collections and schemas within this workspace"
        actions={
          canManage && (
            <Button onClick={() => setOpenCreate(true)}>New Project</Button>
          )
        }
      />

      {projectsQuery.isLoading && <SkeletonTable rows={4} />}
      {projectsQuery.isError && (
        <ErrorState error={projectsQuery.error} onRetry={() => projectsQuery.refetch()} />
      )}

      {projectsQuery.data && projectsQuery.data.items.length === 0 && (
        <EmptyState
          title="No projects yet"
          description="Create a project to start defining collections and ingesting records."
        />
      )}

      {projectsQuery.data && projectsQuery.data.items.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projectsQuery.data.items.map((proj) => (
            <Card key={proj.id} className="flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between">
                  <Link
                    href={`/w/${wid}/projects/${proj.id}`}
                    className="text-base font-semibold hover:underline"
                  >
                    {proj.name}
                  </Link>
                  <Badge tone={proj.status === "active" ? "success" : "warning"}>
                    {proj.status}
                  </Badge>
                </div>
                <div className="mt-1 font-mono text-xs text-[hsl(var(--muted-foreground))]">
                  {proj.slug}
                </div>
              </div>
              <div className="mt-4 flex justify-end">
                <Link href={`/w/${wid}/projects/${proj.id}`}>
                  <Button size="sm" variant="secondary">
                    Open project
                  </Button>
                </Link>
              </div>
            </Card>
          ))}
        </div>
      )}

      <Modal open={openCreate} onClose={() => setOpenCreate(false)} title="Create Project">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            createMutation.mutate();
          }}
          className="space-y-4"
        >
          <div>
            <label htmlFor="p-name" className="mb-1 block text-sm font-medium">
              Project Name
            </label>
            <Input
              id="p-name"
              required
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setSlug(
                  e.target.value
                    .toLowerCase()
                    .replace(/[^a-z0-9_-]+/g, "-")
                    .replace(/^-+|-+$/g, "")
                );
              }}
            />
          </div>
          <div>
            <label htmlFor="p-slug" className="mb-1 block text-sm font-medium">
              Slug
            </label>
            <Input
              id="p-slug"
              required
              minLength={3}
              value={slug}
              onChange={(e) => setSlug(e.target.value.toLowerCase())}
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setOpenCreate(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={createMutation.isPending}>
              {createMutation.isPending ? "Creating..." : "Create"}
            </Button>
          </div>
        </form>
      </Modal>
    </AppShell>
  );
}
