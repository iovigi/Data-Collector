"use client";

import React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQueries, useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import type { Collection, Project } from "@/lib/api/types";
import { AppShell } from "@/components/layout/AppShell";
import { Badge, Button, Card, EmptyState, ErrorState, PageHeader, SkeletonTable } from "@/components/ui/primitives";

export default function WorkspaceCollectionsPage() {
  const { workspaceId: wid } = useParams<{ workspaceId: string }>();

  const projectsQuery = useQuery({
    queryKey: ["projects", wid],
    queryFn: () => apiFetch<{ items: Project[] }>(`/workspaces/${wid}/projects`),
  });

  const projects = projectsQuery.data?.items ?? [];
  const colQueries = useQueries({
    queries: projects.map((p) => ({
      queryKey: ["collections", wid, p.id],
      queryFn: () => apiFetch<{ items: Collection[] }>(`/projects/${p.id}/collections`),
      enabled: projects.length > 0,
    })),
  });

  const isLoading = projectsQuery.isLoading || colQueries.some((q) => q.isLoading);
  const allCollections: Array<Collection & { projectName: string }> = [];
  projects.forEach((p, idx) => {
    const items = colQueries[idx]?.data?.items ?? [];
    for (const c of items) {
      allCollections.push({ ...c, projectName: p.name });
    }
  });

  return (
    <AppShell workspaceId={wid}>
      <PageHeader
        title="Collections"
        subtitle="Browse schemas and launch Data Explorer across projects"
        actions={
          <Link href={`/w/${wid}/projects`}>
            <Button size="sm" variant="secondary">
              Manage Projects
            </Button>
          </Link>
        }
      />

      {isLoading && <SkeletonTable rows={4} />}
      {projectsQuery.isError && <ErrorState error={projectsQuery.error} />}
      {!isLoading && allCollections.length === 0 && (
        <EmptyState
          title="No collections found"
          description="Open a project to create your first schema-validated collection."
          action={
            <Link href={`/w/${wid}/projects`}>
              <Button size="sm">Go to Projects</Button>
            </Link>
          }
        />
      )}

      {allCollections.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {allCollections.map((col) => (
            <Card key={col.id}>
              <div className="flex items-center justify-between">
                <div className="font-semibold">{col.slug}</div>
                <Badge tone="primary">v{col.schema_version}</Badge>
              </div>
              <div className="mt-1 text-xs text-[hsl(var(--muted-foreground))]">
                Project: {col.projectName} · Retention: {col.retention_days}d
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
    </AppShell>
  );
}
