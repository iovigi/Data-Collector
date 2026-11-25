# ChatGPT

See [setup.md](setup.md) for the full guide; the admin MCP page shows the exact values.

1. Settings → Apps & Connectors → Advanced settings → turn on **Developer mode**.
2. Apps & Connectors → **Create**: name `Data Collector`, MCP server URL `<MCP_PUBLIC_URL>`,
   Authentication **OAuth**. Accept the custom-connector notice, Create, then Connect.
3. Sign in, choose the workspace, Approve.
4. In a chat, choose Developer mode from the **+** menu and enable Data Collector.

ChatGPT registers itself (dynamic client registration) with
`https://chatgpt.com/connector_platform_oauth_redirect`; nothing needs to be preconfigured
on the server.
