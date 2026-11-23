"use client";

import React, { useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import type { ApiKeyItem, WorkspaceCapabilities } from "@/lib/api/types";
import { AppShell } from "@/components/layout/AppShell";
import { useToast } from "@/components/providers";
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  CopyButton,
  EmptyState,
  ErrorState,
  Input,
  Modal,
  PageHeader,
  PermissionDenied,
  SkeletonTable,
} from "@/components/ui/primitives";

const ALL_SCOPES = [
  "workspace:read",
  "collection:read",
  "collection:manage",
  "records:read",
  "records:write",
  "records:delete",
  "jobs:read",
  "jobs:create",
  "export:read",
  "audit:read",
];

export default function ApiKeysPage() {
  const { workspaceId: wid } = useParams<{ workspaceId: string }>();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const [openCreate, setOpenCreate] = useState(false);
  const [name, setName] = useState("");
  const [expiresDays, setExpiresDays] = useState(90);
  const [selectedScopes, setSelectedScopes] = useState<string[]>([
    "workspace:read",
    "collection:read",
    "records:read",
  ]);
  const [collectionIdsText, setCollectionIdsText] = useState("");
  const [revealedSecret, setRevealedSecret] = useState<string | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<ApiKeyItem | null>(null);

  const capsQuery = useQuery({
    queryKey: ["capabilities", wid],
    queryFn: () => apiFetch<WorkspaceCapabilities>(`/workspaces/${wid}/capabilities`),
  });

  const canManageKeys = capsQuery.data?.features.can_create_keys ?? false;

  const keysQuery = useQuery({
    queryKey: ["keys", wid],
    queryFn: () => apiFetch<{ items: ApiKeyItem[] }>(`/keys?workspace_id=${wid}`),
    enabled: canManageKeys,
  });

  const createMutation = useMutation({
    mutationFn: () => {
      const allowed = collectionIdsText
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      return apiFetch<ApiKeyItem>("/keys", {
        method: "POST",
        body: {
          workspace_id: wid,
          name: name.trim(),
          scopes: selectedScopes,
          allowed_collection_ids: allowed.length > 0 ? allowed : null,
          expires_in_days: expiresDays,
        },
      });
    },
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["keys", wid] });
      setOpenCreate(false);
      setName("");
      setRevealedSecret(res.api_key ?? null);
      toast({ title: "API key created", variant: "success" });
    },
    onError: (err: Error) =>
      toast({ title: "Create key failed", description: err.message, variant: "error" }),
  });

  const revokeMutation = useMutation({
    mutationFn: (kid: string) =>
      apiFetch(`/keys/${kid}/revoke`, { method: "POST", body: { workspace_id: wid } }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["keys", wid] });
      setRevokeTarget(null);
      toast({ title: "API key revoked", variant: "success" });
    },
  });

  return (
    <AppShell workspaceId={wid}>
      <PageHeader
        title="API Keys"
        subtitle="Scoped, revocable credentials for REST clients and local MCP stdio"
        actions={
          canManageKeys && (
            <Button onClick={() => setOpenCreate(true)}>Create API Key</Button>
          )
        }
      />

      {capsQuery.isLoading && <SkeletonTable rows={3} />}
      {capsQuery.data && !canManageKeys && (
        <PermissionDenied message="Only workspace owners with keys:manage scope can view or issue API keys." />
      )}

      {canManageKeys && keysQuery.isLoading && <SkeletonTable rows={4} />}
      {canManageKeys && keysQuery.isError && <ErrorState error={keysQuery.error} />}
      {canManageKeys && keysQuery.data && keysQuery.data.items.length === 0 && (
        <EmptyState
          title="No API keys yet"
          description="Create a least-privilege API key for automation or local MCP stdio."
        />
      )}

      {canManageKeys && keysQuery.data && keysQuery.data.items.length > 0 && (
        <Card className="overflow-x-auto p-0">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-[hsl(var(--border))] bg-[hsl(var(--surface))] text-xs uppercase text-[hsl(var(--muted-foreground))]">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Prefix</th>
                <th className="px-4 py-3">Scopes</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[hsl(var(--border))]">
              {keysQuery.data.items.map((k) => (
                <tr key={k.id}>
                  <td className="px-4 py-2.5 font-medium">{k.name}</td>
                  <td className="px-4 py-2.5 font-mono text-xs">{k.prefix}</td>
                  <td className="px-4 py-2.5 text-xs">{k.scopes.join(", ")}</td>
                  <td className="px-4 py-2.5">
                    <Badge tone={k.revoked_at ? "danger" : "success"}>
                      {k.revoked_at ? "Revoked" : "Active"}
                    </Badge>
                  </td>
                  <td className="px-4 py-2.5">
                    {!k.revoked_at && (
                      <Button size="sm" variant="danger" onClick={() => setRevokeTarget(k)}>
                        Revoke
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* Create Key Modal */}
      <Modal open={openCreate} onClose={() => setOpenCreate(false)} title="Create Scoped API Key">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            createMutation.mutate();
          }}
          className="space-y-4"
        >
          <div>
            <label htmlFor="k-name" className="mb-1 block text-sm font-medium">
              Key Name
            </label>
            <Input
              id="k-name"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="claude-desktop-ro"
            />
          </div>
          <div>
            <label htmlFor="k-exp" className="mb-1 block text-sm font-medium">
              Expires in (days)
            </label>
            <Input
              id="k-exp"
              type="number"
              min={1}
              max={365}
              value={expiresDays}
              onChange={(e) => setExpiresDays(Number(e.target.value))}
            />
          </div>
          <div>
            <div className="mb-1 text-sm font-medium">Scopes (least-privilege recommended)</div>
            <div className="grid grid-cols-2 gap-1.5 text-xs">
              {ALL_SCOPES.map((sc) => (
                <label key={sc} className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={selectedScopes.includes(sc)}
                    onChange={(e) =>
                      setSelectedScopes((prev) =>
                        e.target.checked ? [...prev, sc] : prev.filter((x) => x !== sc)
                      )
                    }
                  />
                  <span>{sc}</span>
                </label>
              ))}
            </div>
          </div>
          <div>
            <label htmlFor="k-cols" className="mb-1 block text-sm font-medium">
              Optional Collection IDs Allowlist (comma-separated)
            </label>
            <Input
              id="k-cols"
              value={collectionIdsText}
              onChange={(e) => setCollectionIdsText(e.target.value)}
              placeholder="Leave blank for all workspace collections"
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setOpenCreate(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={createMutation.isPending}>
              Create Key
            </Button>
          </div>
        </form>
      </Modal>

      {/* One-time Secret Reveal Modal */}
      <Modal
        open={Boolean(revealedSecret)}
        onClose={() => setRevealedSecret(null)}
        title="Copy Your API Key Now"
      >
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          This plaintext key is shown <strong>only once</strong> and cannot be recovered later.
        </p>
        <div className="mt-3 flex items-center justify-between gap-2 rounded border border-[hsl(var(--border))] bg-[hsl(var(--surface))] p-3">
          <code className="break-all text-xs">{revealedSecret}</code>
          {revealedSecret && <CopyButton text={revealedSecret} />}
        </div>
        <div className="mt-4 flex justify-end">
          <Button onClick={() => setRevealedSecret(null)}>I have saved this key</Button>
        </div>
      </Modal>

      <ConfirmDialog
        open={Boolean(revokeTarget)}
        onClose={() => setRevokeTarget(null)}
        onConfirm={() => revokeTarget && revokeMutation.mutate(revokeTarget.id)}
        title="Revoke API Key"
        description={`Immediately revoke "${revokeTarget?.name ?? ""}" (${revokeTarget?.prefix ?? ""})? Any MCP or REST client using it will receive 401.`}
        confirmLabel="Revoke Key"
        danger
        loading={revokeMutation.isPending}
      />
    </AppShell>
  );
}
