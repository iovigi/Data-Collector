import { describe, expect, it } from "vitest";
import {
  TOKEN_PLACEHOLDER,
  buildGuides,
  claudeCodeOauthCommand,
  claudeCodeTokenCommand,
  genericHttpConfig,
  type McpConnectionInfo,
} from "@/lib/mcp/snippets";

const INFO: McpConnectionInfo = {
  mcp_url: "https://data.example.test/mcp",
  server_name: "data-collector",
  workspace: { id: "6b063983504ba8645c1c5beb", slug: "acme", name: "Acme" },
  oauth: {
    mode: "builtin",
    protected_resource_metadata: "https://data.example.test/.well-known/oauth-protected-resource",
    authorization_server_metadata: "https://data.example.test/.well-known/oauth-authorization-server",
    registration_endpoint: "https://data.example.test/oauth/register",
    token_endpoint: "https://data.example.test/oauth/token",
    dynamic_client_registration: true,
    pkce: "S256",
  },
  writes_enabled: false,
  default_scopes: ["workspace:read", "collection:read", "records:read"],
  available_scopes: [],
  tools: ["dc_aggregate"],
  token_prefix: "dcp_",
};

describe("MCP snippets", () => {
  it("builds the exact Claude Code commands from the server URL", () => {
    expect(claudeCodeOauthCommand(INFO)).toBe(
      "claude mcp add --transport http data-collector https://data.example.test/mcp"
    );
    expect(claudeCodeTokenCommand(INFO, "dcp_ab12.secret")).toBe(
      'claude mcp add --transport http data-collector https://data.example.test/mcp --header "Authorization: Bearer dcp_ab12.secret"'
    );
    expect(claudeCodeTokenCommand(INFO)).toContain(TOKEN_PLACEHOLDER);
  });

  it("emits valid JSON with the header for generic clients", () => {
    const cfg = JSON.parse(genericHttpConfig(INFO, "dcp_x.y"));
    expect(cfg.mcpServers["data-collector"]).toEqual({
      type: "http",
      url: "https://data.example.test/mcp",
      headers: { Authorization: "Bearer dcp_x.y" },
    });
  });

  it("has one guide per client and never hard-codes a host", () => {
    const guides = buildGuides(INFO, null);
    expect(guides.map((g) => g.id)).toEqual(["claude-ai", "claude-code", "chatgpt", "generic", "server"]);
    const text = JSON.stringify(guides);
    expect(text).not.toContain("devart");
    expect(text).toContain("https://data.example.test/mcp");
    expect(text).toContain("Acme (acme)");
    // The server-side stdio option no longer asks remote users for database URLs.
    const server = guides.find((g) => g.id === "server")!;
    expect(server.snippets[0]!.text).not.toMatch(/MONGODB_URI|REDIS_URL/);
  });

  it("fills a freshly created token into the header snippets", () => {
    const guides = buildGuides(INFO, "dcp_new.token");
    const code = guides.find((g) => g.id === "claude-code")!;
    expect(code.snippets[1]!.text).toContain("Bearer dcp_new.token");
  });
});
