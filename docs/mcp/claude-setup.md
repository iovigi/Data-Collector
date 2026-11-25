# Claude (claude.ai, Claude Desktop, Claude Code)

See [setup.md](setup.md) for the full guide; the admin MCP page shows the exact values.

- **claude.ai / Claude Desktop:** Settings → Connectors → *Add custom connector* → name
  `Data Collector`, URL `<MCP_PUBLIC_URL>` → Add → Connect → sign in, choose the workspace,
  Approve. Enable the connector in a chat from the tools menu.
- **Claude Code (OAuth):** `claude mcp add --transport http data-collector <MCP_PUBLIC_URL>`,
  then `/mcp` in Claude Code → Authenticate.
- **Claude Code (token, no browser):** create an MCP token on the admin MCP page, then
  `claude mcp add --transport http data-collector <MCP_PUBLIC_URL> --header "Authorization: Bearer dcp_…"`.
- **Claude Desktop config file:** it only runs stdio servers; use the `mcp-remote` bridge
  config shown on the MCP page.
