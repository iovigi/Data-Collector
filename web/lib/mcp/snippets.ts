/**
 * Connection instructions and copyable snippets for MCP clients.
 * Every value is derived from the server's /mcp/connection-info (MCP_PUBLIC_URL, workspace),
 * never hard-coded, so the page is correct for any deployment.
 */

export interface McpConnectionInfo {
  mcp_url: string;
  server_name: string;
  workspace: { id: string; slug: string; name: string };
  oauth: {
    mode: string;
    protected_resource_metadata: string;
    authorization_server_metadata: string;
    registration_endpoint: string | null;
    token_endpoint: string | null;
    dynamic_client_registration: boolean;
    pkce: string;
  };
  writes_enabled: boolean;
  default_scopes: string[];
  available_scopes: string[];
  tools: string[];
  token_prefix: string;
}

export interface ClientGuide {
  id: string;
  title: string;
  auth: "oauth" | "token" | "oauth-or-token" | "server";
  steps: string[];
  snippets: Array<{ label: string; text: string }>;
  note?: string;
}

export const TOKEN_PLACEHOLDER = "<YOUR_MCP_TOKEN>";

export function bearer(token: string | null | undefined): string {
  return `Bearer ${token || TOKEN_PLACEHOLDER}`;
}

export function claudeCodeOauthCommand(info: McpConnectionInfo): string {
  return `claude mcp add --transport http ${info.server_name} ${info.mcp_url}`;
}

export function claudeCodeTokenCommand(info: McpConnectionInfo, token?: string | null): string {
  return `claude mcp add --transport http ${info.server_name} ${info.mcp_url} --header "Authorization: ${bearer(token)}"`;
}

export function genericHttpConfig(info: McpConnectionInfo, token?: string | null): string {
  return JSON.stringify(
    {
      mcpServers: {
        [info.server_name]: {
          type: "http",
          url: info.mcp_url,
          headers: { Authorization: bearer(token) },
        },
      },
    },
    null,
    2
  );
}

export function claudeDesktopBridgeConfig(info: McpConnectionInfo, token?: string | null): string {
  return JSON.stringify(
    {
      mcpServers: {
        [info.server_name]: {
          command: "npx",
          args: ["-y", "mcp-remote", info.mcp_url, "--header", `Authorization:${bearer(token)}`],
        },
      },
    },
    null,
    2
  );
}

export function serverStdioConfig(info: McpConnectionInfo): string {
  return JSON.stringify(
    {
      mcpServers: {
        [info.server_name]: {
          command: "dc-mcp-stdio",
          env: { DATA_COLLECTOR_API_KEY: "<LEAST_PRIVILEGE_API_KEY>" },
        },
      },
    },
    null,
    2
  );
}

export function buildGuides(info: McpConnectionInfo, token?: string | null): ClientGuide[] {
  const url = info.mcp_url;
  const ws = `${info.workspace.name} (${info.workspace.slug})`;
  const oauthOk = info.oauth.dynamic_client_registration;
  return [
    {
      id: "claude-ai",
      title: "claude.ai and Claude Desktop",
      auth: "oauth",
      steps: [
        "Open Settings → Connectors (claude.ai or the Claude Desktop app).",
        "Click “Add custom connector”.",
        `Name: Data Collector. Remote MCP server URL: ${url}`,
        "Click Add, then Connect. A Data Collector sign-in window opens.",
        `Sign in, choose the workspace ${ws}, keep it read-only, and click Approve.`,
        "In a chat, enable the connector from the tools menu and ask your question.",
      ],
      snippets: [{ label: "Server URL", text: url }],
      note: oauthOk
        ? undefined
        : "This server uses an external OAuth provider; register the client there first.",
    },
    {
      id: "claude-code",
      title: "Claude Code",
      auth: "oauth-or-token",
      steps: [
        "Sign in with OAuth: run the first command, then type /mcp inside Claude Code and choose Authenticate.",
        "Or, without a browser: create an MCP token below and run the second command.",
        "Check with: claude mcp list",
      ],
      snippets: [
        { label: "OAuth (browser sign-in)", text: claudeCodeOauthCommand(info) },
        { label: "MCP token (header)", text: claudeCodeTokenCommand(info, token) },
      ],
    },
    {
      id: "chatgpt",
      title: "ChatGPT (connector / developer mode)",
      auth: "oauth",
      steps: [
        "Open Settings → Apps & Connectors → Advanced settings and turn on Developer mode.",
        "Back in Apps & Connectors, click Create.",
        `Name: Data Collector. MCP server URL: ${url}. Authentication: OAuth.`,
        "Accept the custom-connector notice and click Create, then Connect.",
        `Sign in, choose the workspace ${ws}, and click Approve.`,
        "In a chat, pick Developer mode from the + menu and enable Data Collector.",
      ],
      snippets: [{ label: "MCP server URL", text: url }],
    },
    {
      id: "generic",
      title: "Other MCP clients (Streamable HTTP)",
      auth: "oauth-or-token",
      steps: [
        `Transport: Streamable HTTP at ${url}.`,
        "Clients that support OAuth discover everything from the URL (RFC 9728 metadata, dynamic registration, PKCE S256).",
        "Clients that take a header: create an MCP token below and use the JSON config.",
        "Claude Desktop config file (stdio only): use the mcp-remote bridge config.",
      ],
      snippets: [
        { label: "JSON config with header", text: genericHttpConfig(info, token) },
        { label: "Claude Desktop config via mcp-remote", text: claudeDesktopBridgeConfig(info, token) },
        { label: "Protected resource metadata", text: info.oauth.protected_resource_metadata },
      ],
    },
    {
      id: "server",
      title: "On the server itself (stdio)",
      auth: "server",
      steps: [
        "Only for processes running on the Data Collector host: they reach MongoDB and Redis through the server's own environment.",
        "Use a least-privilege workspace API key from the API Keys page.",
      ],
      snippets: [{ label: "stdio config", text: serverStdioConfig(info) }],
    },
  ];
}

export const SCOPE_LABELS: Record<string, string> = {
  "workspace:read": "See the workspace and its projects",
  "collection:read": "See collections, fields and schemas",
  "records:read": "Read records and run aggregations",
  "records:write": "Create and change records",
  "records:delete": "Delete records (two-step)",
  "jobs:read": "See import/export jobs",
  "jobs:create": "Start imports and exports",
  "export:read": "Export data",
};

export const WRITE_SCOPES = ["records:write", "records:delete", "jobs:create"];
