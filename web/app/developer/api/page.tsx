import React from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import { AppShell } from "@/components/layout/AppShell";
import { Badge, Card, ErrorState, PageHeader, SkeletonTable } from "@/components/ui/primitives";

interface OpenApiDoc {
  openapi: string;
  info: { title: string; version: string; description?: string };
  paths: Record<string, Record<string, { operationId?: string }>>;
}

export default function DeveloperApiPage() {
  const specQuery = useQuery({
    queryKey: ["openapi"],
    queryFn: () => apiFetch<OpenApiDoc>("/openapi.json"),
  });

  return (
    <AppShell>
      <PageHeader
        title="Developer & API Reference"
        subtitle="Live OpenAPI 3.1.0 contract served by Flask /api/v1/openapi.json"
      />
      {specQuery.isLoading && <SkeletonTable rows={6} />}
      {specQuery.isError && <ErrorState error={specQuery.error} />}
      {specQuery.data && (
        <Card className="space-y-3">
          <div className="flex items-center gap-2">
            <span className="font-semibold">{specQuery.data.info.title}</span>
            <Badge tone="primary">OpenAPI {specQuery.data.openapi}</Badge>
          </div>
          <div className="divide-y divide-[hsl(var(--border))] text-xs">
            {Object.entries(specQuery.data.paths).map(([path, methods]) => (
              <div key={path} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <code className="font-mono">{path}</code>
                <div className="flex gap-1.5">
                  {Object.keys(methods).map((m) => (
                    <Badge key={m} tone="neutral">
                      {m.toUpperCase()}
                    </Badge>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </AppShell>
  );
}
