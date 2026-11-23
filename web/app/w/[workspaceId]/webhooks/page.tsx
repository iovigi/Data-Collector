"use client";

import React, { useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import type { WebhookDelivery, WebhookItem, WorkspaceCapabilities } from "@/lib/api/types";
import { AppShell } from "@/components/layout/AppShell";
import { useToast } from "@/components/providers";
import {
  Badge,
  Button,
  Card,
  CopyButton,
  EmptyState,
  ErrorState,
  Input,
  Modal,
  PageHeader,
  SkeletonTable,
} from "@/components/ui/primitives";

const EVENTS = [
  "record.created",
  "record.updated",
  "record.deleted",
  "job.completed",
  "job.failed",
];

export default function WebhooksPage() {
  const { workspaceId: wid } = useParams<{ workspaceId: string }>();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const [openCreate, setOpenCreate] = useState(false);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("https://");
  const [events, setEvents] = useState<string[]>(["record.created"]);
  const [revealedSecret, setRevealedSecret] = useState<string | null>(null);
  const [selectedHookId, setSelectedHookId] = useState<string | null>(null);

  const hooksQuery = useQuery({
    queryKey: ["webhooks", wid],
    queryFn: () => apiFetch<{ items: WebhookItem[] }>(`/workspaces/${wid}/webhooks`),
  });

  const capsQuery = useQuery({
    queryKey: ["capabilities", wid],
    queryFn: () => apiFetch<WorkspaceCapabilities>(`/workspaces/${wid}/capabilities`),
  });

  const deliveriesQuery = useQuery({
    queryKey: ["webhook-deliveries", wid, selectedHookId],
    queryFn: () =>
      apiFetch<{ items: WebhookDelivery[] }>(
        `/workspaces/${wid}/webhooks/${selectedHookId}/deliveries`
      ),
    enabled: Boolean(selectedHookId),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      apiFetch<WebhookItem>(`/workspaces/${wid}/webhooks`, {
        method: "POST",
        body: { name: name.trim(), url: url.trim(), events },
      }),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["webhooks", wid] });
      setOpenCreate(false);
      setName("");
      setUrl("https://");
      setRevealedSecret(res.signing_secret ?? null);
      toast({ title: "Webhook created", variant: "success" });
    },
    onError: (err: Error) =>
      toast({ title: "Create webhook failed", description: err.message, variant: "error" }),
  });

  const toggleMutation = useMutation({
    mutationFn: (h: WebhookItem) =>
      apiFetch(`/workspaces/${wid}/webhooks/${h.id}`, {
        method: "PATCH",
        body: { status: h.status === "active" ? "disabled" : "active" },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["webhooks", wid] });
      toast({ title: "Webhook updated", variant: "success" });
    },
  });

  const rotateMutation = useMutation({
    mutationFn: (hid: string) =>
      apiFetch<WebhookItem>(`/workspaces/${wid}/webhooks/${hid}/rotate-secret`, {
        method: "POST",
      }),
    onSuccess: (res) => setRevealedSecret(res.signing_secret ?? null),
  });

  const deleteMutation = useMutation({
    mutationFn: (hid: string) =>
      apiFetch(`/workspaces/${wid}/webhooks/${hid}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["webhooks", wid] });
      toast({ title: "Webhook deleted", variant: "success" });
    },
  });

  const canManage = capsQuery.data?.features.can_manage_webhooks ?? false;

  return (
    <AppShell workspaceId={wid}>
      <PageHeader
        title="Webhooks"
        subtitle="SSRF-protected outbound event deliveries signed with HMAC-SHA256"
        actions={canManage && <Button onClick={() => setOpenCreate(true)}>Add Webhook</Button>}
      />

      {hooksQuery.isLoading && <SkeletonTable rows={4} />}
      {hooksQuery.isError && <ErrorState error={hooksQuery.error} />}
      {hooksQuery.data && hooksQuery.data.items.length === 0 && (
        <EmptyState
          title="No webhooks configured"
          description="Register an HTTPS endpoint to receive signed event notifications."
        />
      )}

      {hooksQuery.data && hooksQuery.data.items.length > 0 && (
        <div className="space-y-3">
          {hooksQuery.data.items.map((h) => (
            <Card key={h.id} className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-semibold">{h.name}</span>
                  <Badge tone={h.status === "active" ? "success" : "warning"}>{h.status}</Badge>
                </div>
                <div className="mt-1 font-mono text-xs text-[hsl(var(--muted-foreground))]">
                  {h.url}
                </div>
                <div className="mt-1 text-xs text-[hsl(var(--muted-foreground))]">
                  Events: {h.events.join(", ")}
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="secondary" onClick={() => setSelectedHookId(h.id)}>
                  Deliveries
                </Button>
                {canManage && (
                  <>
                    <Button size="sm" variant="secondary" onClick={() => toggleMutation.mutate(h)}>
                      {h.status === "active" ? "Disable" : "Enable"}
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => rotateMutation.mutate(h.id)}
                    >
                      Rotate Secret
                    </Button>
                    <Button size="sm" variant="danger" onClick={() => deleteMutation.mutate(h.id)}>
                      Delete
                    </Button>
                  </>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      <Modal open={openCreate} onClose={() => setOpenCreate(false)} title="Create Webhook">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            createMutation.mutate();
          }}
          className="space-y-4"
        >
          <div>
            <label htmlFor="wh-name" className="mb-1 block text-sm font-medium">
              Name
            </label>
            <Input id="wh-name" required value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label htmlFor="wh-url" className="mb-1 block text-sm font-medium">
              HTTPS Endpoint URL
            </label>
            <Input id="wh-url" required value={url} onChange={(e) => setUrl(e.target.value)} />
          </div>
          <div>
            <div className="mb-1 text-sm font-medium">Events</div>
            <div className="space-y-1 text-xs">
              {EVENTS.map((ev) => (
                <label key={ev} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={events.includes(ev)}
                    onChange={(e) =>
                      setEvents((prev) =>
                        e.target.checked ? [...prev, ev] : prev.filter((x) => x !== ev)
                      )
                    }
                  />
                  <span>{ev}</span>
                </label>
              ))}
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setOpenCreate(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={createMutation.isPending}>
              Create
            </Button>
          </div>
        </form>
      </Modal>

      <Modal
        open={Boolean(revealedSecret)}
        onClose={() => setRevealedSecret(null)}
        title="Webhook Signing Secret"
      >
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          Verify <code>X-DC-Signature</code> using this HMAC-SHA256 secret. Shown once only.
        </p>
        <div className="mt-3 flex items-center justify-between gap-2 rounded border border-[hsl(var(--border))] bg-[hsl(var(--surface))] p-3">
          <code className="break-all text-xs">{revealedSecret}</code>
          {revealedSecret && <CopyButton text={revealedSecret} />}
        </div>
        <div className="mt-4 flex justify-end">
          <Button onClick={() => setRevealedSecret(null)}>Done</Button>
        </div>
      </Modal>

      <Modal
        open={Boolean(selectedHookId)}
        onClose={() => setSelectedHookId(null)}
        title="Recent Deliveries"
      >
        {deliveriesQuery.isLoading && <SkeletonTable rows={3} />}
        {deliveriesQuery.data && deliveriesQuery.data.items.length === 0 && (
          <p className="text-sm text-[hsl(var(--muted-foreground))]">No deliveries yet.</p>
        )}
        {deliveriesQuery.data && deliveriesQuery.data.items.length > 0 && (
          <div className="max-h-64 space-y-2 overflow-auto text-xs">
            {deliveriesQuery.data.items.map((d) => (
              <div
                key={d.id}
                className="flex items-center justify-between rounded border border-[hsl(var(--border))] p-2"
              >
                <span>{d.event}</span>
                <Badge tone={d.status === "delivered" ? "success" : "danger"}>
                  {d.status} ({d.http_status})
                </Badge>
              </div>
            ))}
          </div>
        )}
      </Modal>
    </AppShell>
  );
}
