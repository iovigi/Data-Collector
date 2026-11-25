import React, { useMemo, useState } from "react";
import { useParams } from "@/lib/router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, KeyRound, PlugZap, XCircle } from "lucide-react";
import { apiFetch } from "@/lib/api/client";
import type { McpConnectionCheck, McpGrant, McpToken, WorkspaceCapabilities } from "@/lib/api/types";
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
  PageHeader,
  SkeletonTable,
} from "@/components/ui/primitives";
import {
  SCOPE_LABELS,
  WRITE_SCOPES,
  buildGuides,
  type ClientGuide,
  type McpConnectionInfo,
} from "@/lib/mcp/snippets";

function fmt(ts: string | null | undefined): string {
  return ts ? new Date(ts).toLocaleString() : "never";
}

function Snippet({ label, text }: { label: string; text: string }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-[hsl(var(--muted-foreground))]">{label}</span>
        <CopyButton text={text} label="Copy" />
      </div>
      <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--surface))] p-2 font-mono text-xs">
        {text}
      </pre>
    </div>
  );
}

function GuideCard({ guide }: { guide: ClientGuide }) {
  const tone = guide.auth === "server" ? "neutral" : "primary";
  const authLabel = {
    oauth: "Sign in with OAuth",
    token: "MCP token",
    "oauth-or-token": "OAuth or MCP token",
    server: "Server only",
  }[guide.auth];
  return (
    <section data-testid={`guide-${guide.id}`}>
    <Card className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-base font-semibold">{guide.title}</h2>
        <Badge tone={tone}>{authLabel}</Badge>
      </div>
      <ol className="list-decimal space-y-1 pl-5 text-sm">
        {guide.steps.map((s) => (
          <li key={s}>{s}</li>
        ))}
      </ol>
      {guide.snippets.map((s) => (
        <Snippet key={s.label} label={s.label} text={s.text} />
      ))}
      {guide.note && <p className="text-xs text-[hsl(var(--muted-foreground))]">{guide.note}</p>}
    </Card>
    </section>
  );
}

export function ConnectionCheckCard({ wid }: { wid: string }) {
  const check = useMutation({
    mutationFn: () =>
      apiFetch<McpConnectionCheck>(`/workspaces/${wid}/mcp/connection-check`, { method: "POST" }),
  });
  return (
    <Card className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold">Test connection</h2>
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            Calls the public MCP URL the way Claude or ChatGPT would: OAuth metadata, token endpoint,
            sign-in challenge and tool listing.
          </p>
        </div>
        <Button size="sm" onClick={() => check.mutate()} disabled={check.isPending}>
          <PlugZap className="h-3.5 w-3.5" />
          {check.isPending ? "Testing…" : "Test connection"}
        </Button>
      </div>
      {check.isError && <ErrorState error={check.error} />}
      {check.data && (
        <ul className="space-y-1 text-sm" aria-label="Connection check results">
          {check.data.checks.map((c) => (
            <li key={c.check} className="flex items-start gap-2">
              {c.ok ? (
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-green-600" aria-label="passed" />
              ) : (
                <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-[hsl(var(--destructive))]" aria-label="failed" />
              )}
              <span>
                <strong>{c.check}</strong>{" "}
                <span className="text-xs text-[hsl(var(--muted-foreground))]">
                  {c.detail} · {c.ms} ms
                </span>
              </span>
            </li>
          ))}
          {check.data.ok && (
            <li className="pt-1 text-xs text-[hsl(var(--muted-foreground))]">
              {check.data.tools.length} tools reachable from outside.
            </li>
          )}
        </ul>
      )}
    </Card>
  );
}

export function TokensCard({
  wid,
  writesEnabled,
  onCreated,
}: {
  wid: string;
  writesEnabled: boolean;
  onCreated: (token: string) => void;
}) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [name, setName] = useState("Claude Code");
  const [allowWrites, setAllowWrites] = useState(false);
  const [fresh, setFresh] = useState<McpToken | null>(null);

  const tokens = useQuery({
    queryKey: ["mcp-tokens", wid],
    queryFn: () => apiFetch<{ items: McpToken[] }>(`/workspaces/${wid}/mcp/tokens`),
  });
  const create = useMutation({
    mutationFn: () =>
      apiFetch<McpToken>(`/workspaces/${wid}/mcp/tokens`, {
        method: "POST",
        body: {
          name,
          scopes: [
            "workspace:read",
            "collection:read",
            "records:read",
            ...(allowWrites ? ["records:write"] : []),
          ],
        },
      }),
    onSuccess: (t) => {
      setFresh(t);
      if (t.token) onCreated(t.token);
      qc.invalidateQueries({ queryKey: ["mcp-tokens", wid] });
    },
    onError: (e: Error) => toast({ title: "Could not create token", description: e.message, variant: "error" }),
  });
  const revoke = useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/workspaces/${wid}/mcp/tokens/${id}/revoke`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mcp-tokens", wid] });
      toast({ title: "Token revoked", variant: "success" });
    },
  });

  return (
    <Card className="space-y-3">
      <div className="flex items-center gap-2">
        <KeyRound className="h-4 w-4" />
        <h2 className="text-base font-semibold">MCP access tokens</h2>
      </div>
      <p className="text-sm text-[hsl(var(--muted-foreground))]">
        For clients that send a header instead of signing in (Claude Code, scripts). A token belongs
        to you and this workspace, works only on the MCP endpoint, and is read-only unless you allow
        changes.
      </p>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <label className="flex-1 text-sm">
          <span className="mb-1 block text-xs font-medium">Token name</span>
          <Input value={name} onChange={(e) => setName(e.target.value)} required maxLength={120} />
        </label>
        <label
          className="flex items-center gap-2 pb-2 text-sm"
          title={writesEnabled ? "" : "The server does not accept changes from AI clients (MCP_ALLOW_WRITES)"}
        >
          <input
            type="checkbox"
            checked={allowWrites}
            disabled={!writesEnabled}
            onChange={(e) => setAllowWrites(e.target.checked)}
          />
          Allow changes
        </label>
        <Button type="submit" size="sm" disabled={create.isPending || !name.trim()}>
          Create token
        </Button>
      </form>
      {fresh?.token && (
        <div className="space-y-1 rounded-md border border-amber-400 bg-amber-50 p-3 text-sm dark:bg-amber-950/30" role="status">
          <strong>Copy this token now. It will not be shown again.</strong>
          <Snippet label={fresh.name} text={fresh.token} />
        </div>
      )}
      {tokens.isLoading && <SkeletonTable rows={2} />}
      {tokens.data && tokens.data.items.length === 0 && (
        <p className="text-sm text-[hsl(var(--muted-foreground))]">No active tokens.</p>
      )}
      {tokens.data && tokens.data.items.length > 0 && (
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-[hsl(var(--muted-foreground))]">
            <tr>
              <th className="py-1">Name</th>
              <th>Access</th>
              <th>Last used</th>
              <th>Expires</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {tokens.data.items.map((t) => (
              <tr key={t.id} className="border-t border-[hsl(var(--border))]">
                <td className="py-1.5">
                  {t.name} <code className="text-xs">{t.prefix}…</code>
                </td>
                <td>
                  <Badge tone={t.scopes.some((s) => WRITE_SCOPES.includes(s)) ? "warning" : "success"}>
                    {t.scopes.some((s) => WRITE_SCOPES.includes(s)) ? "Read & write" : "Read-only"}
                  </Badge>
                </td>
                <td className="text-xs">{fmt(t.last_used_at)}</td>
                <td className="text-xs">{fmt(t.expires_at)}</td>
                <td className="text-right">
                  <Button size="sm" variant="ghost" onClick={() => revoke.mutate(t.id)}>
                    Revoke
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

function GrantsCard({ wid, showOwner }: { wid: string; showOwner: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const grants = useQuery({
    queryKey: ["mcp-grants", wid],
    queryFn: () => apiFetch<{ items: McpGrant[] }>(`/workspaces/${wid}/mcp/grants`),
  });
  const revoke = useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/workspaces/${wid}/mcp/grants/${id}/revoke`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mcp-grants", wid] });
      toast({ title: "Client disconnected", variant: "success" });
    },
  });
  return (
    <Card className="space-y-3">
      <h2 className="text-base font-semibold">Connected clients</h2>
      <p className="text-sm text-[hsl(var(--muted-foreground))]">
        Apps that signed in with OAuth for this workspace. Disconnecting cuts off access at once,
        including refresh.
      </p>
      {grants.isLoading && <SkeletonTable rows={2} />}
      {grants.isError && <ErrorState error={grants.error} />}
      {grants.data && grants.data.items.length === 0 && (
        <EmptyState title="No connected clients" description="Connect Claude or ChatGPT with one of the guides above." />
      )}
      {grants.data && grants.data.items.length > 0 && (
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-[hsl(var(--muted-foreground))]">
            <tr>
              <th className="py-1">Client</th>
              {showOwner && <th>User</th>}
              <th>Scopes</th>
              <th>Last used</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {grants.data.items.map((g) => (
              <tr key={g.id} className="border-t border-[hsl(var(--border))] align-top">
                <td className="py-1.5">
                  {g.client_name}
                  <div className="text-xs text-[hsl(var(--muted-foreground))]">since {fmt(g.created_at)}</div>
                </td>
                {showOwner && <td className="text-xs">{g.email}</td>}
                <td className="text-xs">{g.scopes.map((s) => SCOPE_LABELS[s] ?? s).join("; ")}</td>
                <td className="text-xs">{fmt(g.last_used_at)}</td>
                <td className="text-right">
                  <Button size="sm" variant="ghost" onClick={() => revoke.mutate(g.id)}>
                    Disconnect
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

export default function McpConnectionsPage() {
  const { workspaceId: wid } = useParams<{ workspaceId: string }>();
  const [token, setToken] = useState<string | null>(null);
  const info = useQuery({
    queryKey: ["mcp-connection-info", wid],
    queryFn: () => apiFetch<McpConnectionInfo>(`/workspaces/${wid}/mcp/connection-info`),
  });
  const caps = useQuery({
    queryKey: ["capabilities", wid],
    queryFn: () => apiFetch<WorkspaceCapabilities>(`/workspaces/${wid}/capabilities`),
  });
  const guides = useMemo(() => (info.data ? buildGuides(info.data, token) : []), [info.data, token]);

  return (
    <AppShell workspaceId={wid}>
      <PageHeader
        title="MCP Connections"
        subtitle="Connect Claude (claude.ai, Desktop, Code), ChatGPT or any MCP client to this workspace"
      />
      {info.isLoading && <SkeletonTable rows={4} />}
      {info.isError && <ErrorState error={info.error} />}
      {info.data && (
        <div className="space-y-6">
          <Card className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">MCP server URL</span>
              <Badge tone={info.data.writes_enabled ? "warning" : "success"}>
                {info.data.writes_enabled ? "Writes allowed when granted" : "Read-only server"}
              </Badge>
              <Badge tone="neutral">{info.data.tools.length} tools</Badge>
            </div>
            <Snippet label={`Workspace: ${info.data.workspace.name}`} text={info.data.mcp_url} />
          </Card>
          <ConnectionCheckCard wid={wid} />
          <div className="grid gap-6 lg:grid-cols-2">
            {guides.map((g) => (
              <GuideCard key={g.id} guide={g} />
            ))}
          </div>
          <TokensCard wid={wid} writesEnabled={info.data.writes_enabled} onCreated={setToken} />
          <GrantsCard wid={wid} showOwner={caps.data?.features.can_manage_all_mcp_connections ?? false} />
        </div>
      )}
    </AppShell>
  );
}
