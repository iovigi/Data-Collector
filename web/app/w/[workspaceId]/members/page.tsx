import React, { useState } from "react";
import { useParams } from "@/lib/router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import type { InvitationItem, WorkspaceCapabilities, WorkspaceMember } from "@/lib/api/types";
import { AppShell } from "@/components/layout/AppShell";
import { useToast } from "@/components/providers";
import {
  Badge,
  Button,
  Card,
  CopyButton,
  ErrorState,
  Input,
  Modal,
  PageHeader,
  Select,
  SkeletonTable,
} from "@/components/ui/primitives";

export default function MembersPage() {
  const { workspaceId: wid } = useParams<{ workspaceId: string }>();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const [openInvite, setOpenInvite] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"admin" | "editor" | "viewer">("editor");
  const [createdInvite, setCreatedInvite] = useState<InvitationItem | null>(null);

  const capsQuery = useQuery({
    queryKey: ["capabilities", wid],
    queryFn: () => apiFetch<WorkspaceCapabilities>(`/workspaces/${wid}/capabilities`),
  });
  const canManage = capsQuery.data?.features.can_manage_members ?? false;

  const membersQuery = useQuery({
    queryKey: ["members", wid],
    queryFn: () => apiFetch<{ items: WorkspaceMember[] }>(`/workspaces/${wid}/members`),
  });

  const invitesQuery = useQuery({
    queryKey: ["invitations", wid],
    queryFn: () => apiFetch<{ items: InvitationItem[] }>(`/workspaces/${wid}/invitations`),
    enabled: canManage,
  });

  const inviteMutation = useMutation({
    mutationFn: () =>
      apiFetch<InvitationItem>(`/workspaces/${wid}/invitations`, {
        method: "POST",
        body: { email: inviteEmail.trim(), role: inviteRole },
      }),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["invitations", wid] });
      setOpenInvite(false);
      setInviteEmail("");
      setCreatedInvite(res);
      toast({ title: "Invitation created", variant: "success" });
    },
    onError: (err: Error) =>
      toast({ title: "Invite failed", description: err.message, variant: "error" }),
  });

  const roleMutation = useMutation({
    mutationFn: ({ pid, role }: { pid: string; role: string }) =>
      apiFetch(`/workspaces/${wid}/members/${pid}`, { method: "PATCH", body: { role } }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["members", wid] });
      toast({ title: "Role updated", variant: "success" });
    },
    onError: (err: Error) =>
      toast({ title: "Role update blocked", description: err.message, variant: "error" }),
  });

  const removeMutation = useMutation({
    mutationFn: (pid: string) =>
      apiFetch(`/workspaces/${wid}/members/${pid}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["members", wid] });
      toast({ title: "Member removed", variant: "success" });
    },
    onError: (err: Error) =>
      toast({ title: "Remove blocked", description: err.message, variant: "error" }),
  });

  return (
    <AppShell workspaceId={wid}>
      <PageHeader
        title="Members & Access"
        subtitle="Manage workspace roles, email invitations, and ownership constraints"
        actions={canManage && <Button onClick={() => setOpenInvite(true)}>Invite Member</Button>}
      />

      {membersQuery.isLoading && <SkeletonTable rows={4} />}
      {membersQuery.isError && <ErrorState error={membersQuery.error} />}
      {membersQuery.data && (
        <Card className="overflow-x-auto p-0">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-[hsl(var(--border))] bg-[hsl(var(--surface))] text-xs uppercase text-[hsl(var(--muted-foreground))]">
              <tr>
                <th className="px-4 py-3">Email</th>
                <th className="px-4 py-3">Principal ID</th>
                <th className="px-4 py-3">Role</th>
                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[hsl(var(--border))]">
              {membersQuery.data.items.map((m) => (
                <tr key={m.id}>
                  <td className="px-4 py-2.5">{m.email ?? "—"}</td>
                  <td className="px-4 py-2.5 font-mono text-xs">{m.principal_id}</td>
                  <td className="px-4 py-2.5">
                    {canManage && m.role !== "owner" ? (
                      <Select
                        aria-label={`Role for ${m.email ?? m.principal_id}`}
                        value={m.role}
                        onChange={(e) =>
                          roleMutation.mutate({ pid: m.principal_id, role: e.target.value })
                        }
                      >
                        <option value="admin">admin</option>
                        <option value="editor">editor</option>
                        <option value="viewer">viewer</option>
                      </Select>
                    ) : (
                      <Badge tone="primary">{m.role}</Badge>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    {canManage && m.role !== "owner" && (
                      <Button
                        size="sm"
                        variant="danger"
                        onClick={() => removeMutation.mutate(m.principal_id)}
                      >
                        Remove
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {canManage && invitesQuery.data && invitesQuery.data.items.length > 0 && (
        <Card className="mt-6">
          <h2 className="mb-3 text-base font-semibold">Pending & Past Invitations</h2>
          <ul className="divide-y divide-[hsl(var(--border))] text-sm">
            {invitesQuery.data.items.map((inv) => (
              <li key={inv.id} className="flex items-center justify-between py-2">
                <span>
                  {inv.email} ({inv.role})
                </span>
                <Badge tone={inv.status === "pending" ? "primary" : "neutral"}>{inv.status}</Badge>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Modal open={openInvite} onClose={() => setOpenInvite(false)} title="Invite Member by Email">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            inviteMutation.mutate();
          }}
          className="space-y-4"
        >
          <div>
            <label htmlFor="inv-email" className="mb-1 block text-sm font-medium">
              Email Address
            </label>
            <Input
              id="inv-email"
              type="email"
              required
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="inv-role" className="mb-1 block text-sm font-medium">
              Role
            </label>
            <Select
              id="inv-role"
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value as "admin" | "editor" | "viewer")}
            >
              <option value="admin">admin</option>
              <option value="editor">editor</option>
              <option value="viewer">viewer</option>
            </Select>
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setOpenInvite(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={inviteMutation.isPending}>
              Create Invitation
            </Button>
          </div>
        </form>
      </Modal>

      <Modal
        open={Boolean(createdInvite)}
        onClose={() => setCreatedInvite(null)}
        title="Invitation Token (Shown Once)"
      >
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          No SMTP provider is configured. Share this invitation ID and one-time token securely with{" "}
          <strong>{createdInvite?.email}</strong>:
        </p>
        {createdInvite && (
          <div className="mt-3 space-y-2 rounded border border-[hsl(var(--border))] bg-[hsl(var(--surface))] p-3 text-xs font-mono">
            <div>Invitation ID: {createdInvite.id}</div>
            <div className="break-all">Token: {createdInvite.invite_token}</div>
            {createdInvite.invite_token && (
              <CopyButton text={createdInvite.invite_token} label="Copy Token" />
            )}
          </div>
        )}
      </Modal>
    </AppShell>
  );
}
