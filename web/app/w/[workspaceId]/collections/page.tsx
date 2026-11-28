import React, { useState } from "react";
import { Link } from "@/lib/router";
import { useParams } from "@/lib/router";
import { useQueries, useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import type { BatchCollectionCountsResponse, Collection, CollectionCountResponse, Project } from "@/lib/api/types";
import { AppShell } from "@/components/layout/AppShell";
import { CountBadge } from "@/components/data/CountBadge";
import { Badge, Button, Card, EmptyState, ErrorState, PageHeader, SkeletonTable } from "@/components/ui/primitives";

const COLLECTIONS_PER_PAGE = 24;

export default function WorkspaceCollectionsPage() {
  const { workspaceId: wid } = useParams<{ workspaceId: string }>();

  return <WorkspaceCollections key={wid} wid={wid} />;
}

function WorkspaceCollections({ wid }: { wid: string }) {
  const [requestedPage, setRequestedPage] = useState(0);
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

  const pageCount = Math.max(1, Math.ceil(allCollections.length / COLLECTIONS_PER_PAGE));
  const page = Math.min(requestedPage, pageCount - 1);
  const visibleCollections = allCollections.slice(
    page * COLLECTIONS_PER_PAGE,
    (page + 1) * COLLECTIONS_PER_PAGE
  );
  const batchIds = visibleCollections.map((collection) => collection.id);
  const failedProjects = colQueries.filter((query) => query.isError);
  const countsQuery = useQuery({
    queryKey: ["collection-counts-batch", wid, batchIds.join(",")],
    queryFn: () =>
      apiFetch<BatchCollectionCountsResponse>("/collections/counts", {
        method: "POST",
        body: { collection_ids: batchIds, include_trash: false },
      }),
    enabled: batchIds.length > 0,
    staleTime: 60_000,
  });

  const countMap = new Map<string, CollectionCountResponse>();
  for (const item of countsQuery.data?.items ?? []) {
    countMap.set(item.collection_id, item);
  }

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
      {projectsQuery.isError && (
        <ErrorState error={projectsQuery.error} onRetry={() => projectsQuery.refetch()} />
      )}
      {failedProjects.map((query, index) => (
        <ErrorState key={index} error={query.error} onRetry={() => query.refetch()} />
      ))}
      {!isLoading && !projectsQuery.isError && failedProjects.length === 0 && allCollections.length === 0 && (
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
          {visibleCollections.map((col) => (
            <Card key={col.id}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 break-words font-semibold">{col.slug}</div>
                <Badge tone="primary">v{col.schema_version}</Badge>
              </div>
              <div className="mt-1 flex flex-wrap items-center justify-between gap-2 text-xs text-[hsl(var(--muted-foreground))]">
                <span>
                  Project: {col.projectName} · Retention: {col.retention_days}d
                </span>
                <CountBadge
                  compact
                  bucket={countMap.get(col.id)?.active}
                  loading={countsQuery.isPending}
                  unavailable={countsQuery.isError}
                  onDemand
                />
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
      {pageCount > 1 && (
        <nav aria-label="Collection pages" className="mt-4 flex flex-wrap items-center justify-between gap-2">
          <span className="text-sm text-[hsl(var(--muted-foreground))]" aria-live="polite">
            Page {page + 1} of {pageCount}
          </span>
          <div className="flex gap-2">
            <Button size="sm" variant="secondary" disabled={page === 0} onClick={() => setRequestedPage(page - 1)}>
              Previous
            </Button>
            <Button size="sm" variant="secondary" disabled={page + 1 === pageCount} onClick={() => setRequestedPage(page + 1)}>
              Next
            </Button>
          </div>
        </nav>
      )}
    </AppShell>
  );
}
