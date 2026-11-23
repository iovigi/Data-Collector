"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Project, Workspace } from "@/lib/api/types";
import { Button, Card, Input, PageHeader } from "@/components/ui/primitives";

function slugify(val: string): string {
  return val
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
}

export default function OnboardingCreateWorkspacePage() {
  const router = useRouter();
  const [wsName, setWsName] = useState("");
  const [wsSlug, setWsSlug] = useState("");
  const [projName, setProjName] = useState("Default Project");
  const [projSlug, setProjSlug] = useState("default-project");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const ws = await apiFetch<Workspace>("/workspaces", {
        method: "POST",
        body: { name: wsName.trim(), slug: wsSlug.trim() },
      });
      await apiFetch<Project>(`/workspaces/${ws.id}/projects`, {
        method: "POST",
        body: { name: projName.trim(), slug: projSlug.trim() },
      });
      window.localStorage.setItem("dc-last-workspace", ws.id);
      router.replace(`/w/${ws.id}/overview`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to initialize workspace");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl px-4 py-12">
      <PageHeader
        title="Create your first workspace"
        subtitle="Workspaces isolate tenants, projects, collections, API keys, and audit logs."
      />
      <Card>
        <form onSubmit={handleCreate} className="space-y-4">
          <div>
            <label htmlFor="ws-name" className="mb-1 block text-sm font-medium">
              Workspace name
            </label>
            <Input
              id="ws-name"
              required
              value={wsName}
              onChange={(e) => {
                setWsName(e.target.value);
                if (!wsSlug || wsSlug === slugify(wsName)) {
                  setWsSlug(slugify(e.target.value));
                }
              }}
              placeholder="Acme Corp"
            />
          </div>
          <div>
            <label htmlFor="ws-slug" className="mb-1 block text-sm font-medium">
              Workspace slug (3–64 lowercase chars)
            </label>
            <Input
              id="ws-slug"
              required
              minLength={3}
              maxLength={64}
              value={wsSlug}
              onChange={(e) => setWsSlug(e.target.value.toLowerCase())}
              placeholder="acme-corp"
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="proj-name" className="mb-1 block text-sm font-medium">
                Initial project name
              </label>
              <Input
                id="proj-name"
                required
                value={projName}
                onChange={(e) => setProjName(e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="proj-slug" className="mb-1 block text-sm font-medium">
                Initial project slug
              </label>
              <Input
                id="proj-slug"
                required
                minLength={3}
                value={projSlug}
                onChange={(e) => setProjSlug(e.target.value.toLowerCase())}
              />
            </div>
          </div>

          {error && (
            <div
              role="alert"
              className="rounded-md border border-[hsl(var(--destructive))] bg-red-500/10 px-3 py-2 text-sm text-[hsl(var(--destructive))]"
            >
              {error}
            </div>
          )}

          <div className="flex justify-end">
            <Button type="submit" disabled={submitting}>
              {submitting ? "Creating..." : "Create workspace & continue"}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
