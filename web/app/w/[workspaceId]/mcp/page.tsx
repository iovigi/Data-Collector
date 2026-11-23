import React from "react";
import { Link } from "@/lib/router";
import { useParams } from "@/lib/router";
import { AppShell } from "@/components/layout/AppShell";
import { Badge, Button, Card, CopyButton, PageHeader } from "@/components/ui/primitives";

export default function McpConnectionsPage() {
  const { workspaceId: wid } = useParams<{ workspaceId: string }>();

  const stdioConfig = JSON.stringify(
    {
      mcpServers: {
        "data-collector": {
          command: "dc-mcp-stdio",
          env: {
            MONGODB_URI: "mongodb://localhost:27017/",
            MONGODB_DB: "data_collector",
            REDIS_URL: "redis://localhost:6379/0",
            DATA_COLLECTOR_API_KEY: "<PASTE_LEAST_PRIVILEGE_API_KEY>",
          },
        },
      },
    },
    null,
    2
  );

  return (
    <AppShell workspaceId={wid}>
      <PageHeader
        title="MCP Connections Center"
        subtitle="Connect Claude Desktop, Claude Code, and ChatGPT to Data Collector 2.0"
        actions={
          <Link href={`/w/${wid}/keys`}>
            <Button size="sm">Create Scoped API Key</Button>
          </Link>
        }
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold">Local Stdio (Claude Code / Claude Desktop)</h2>
            <Badge tone="success">Read-only default</Badge>
          </div>
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            Uses <code>dc-mcp-stdio</code> with a least-privilege API key. Logs are isolated to{" "}
            <code>stderr</code>.
          </p>
          <pre className="overflow-x-auto rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--surface))] p-3 font-mono text-xs">
            {stdioConfig}
          </pre>
          <CopyButton text={stdioConfig} label="Copy stdio config" />
        </Card>

        <Card className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold">Remote Streamable HTTP (ChatGPT / Claude.ai)</h2>
            <Badge tone="warning">External UI: Not verified here</Badge>
          </div>
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            Remote connectors require HTTPS deployment of <code>dc-mcp-http</code> with OAuth 2.1
            PKCE S256 discovery enabled at <code>/.well-known/oauth-protected-resource</code>.
          </p>
          <ul className="list-disc space-y-1 pl-5 text-xs text-[hsl(var(--muted-foreground))]">
            <li>
              Endpoint path: <code>/mcp</code> (Streamable HTTP)
            </li>
            <li>
              Required OAuth scopes: <code>workspace:read collection:read records:read</code>
            </li>
            <li>
              Destructive deletes require <code>dc_prepare_delete_record</code> +{" "}
              <code>dc_delete_record</code>
            </li>
          </ul>
        </Card>
      </div>
    </AppShell>
  );
}
