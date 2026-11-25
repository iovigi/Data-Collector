import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ConnectionCheckCard, TokensCard } from "@/app/w/[workspaceId]/mcp/page";

const WID = "6b063983504ba8645c1c5beb";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("MCP tokens panel", () => {
  it("creates a read-only token by default and shows it once", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/mcp/tokens") && init?.method === "POST") {
        return json(
          {
            id: "6b0000000000000000000001",
            name: "Claude Code",
            prefix: "dcp_ab12",
            scopes: JSON.parse(String(init.body)).scopes,
            token: "dcp_ab12.s3cret",
            expires_at: "2027-01-01T00:00:00Z",
            last_used_at: null,
          },
          201
        );
      }
      return json({ items: [] });
    });
    const onCreated = vi.fn();
    wrap(<TokensCard wid={WID} writesEnabled={false} onCreated={onCreated} />);

    expect(screen.getByLabelText("Allow changes")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Create token" }));

    await screen.findByText("dcp_ab12.s3cret");
    expect(screen.getByText(/will not be shown again/)).toBeInTheDocument();
    expect(onCreated).toHaveBeenCalledWith("dcp_ab12.s3cret");
    const post = fetchMock.mock.calls.find(([, i]) => i?.method === "POST")!;
    expect(String(post[0])).toBe(`/api/backend/workspaces/${WID}/mcp/tokens`);
    expect(JSON.parse(String(post[1]!.body)).scopes).toEqual([
      "workspace:read",
      "collection:read",
      "records:read",
    ]);
  });
});

describe("Test connection", () => {
  it("lists each outside-in check with its result", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      json({
        mcp_url: "https://data.example.test/mcp",
        ok: false,
        tools: [],
        checks: [
          { check: "Protected resource metadata", ok: true, detail: "HTTP 200", ms: 12 },
          { check: "Tool listing", ok: false, detail: "initialize HTTP 502", ms: 40 },
        ],
      })
    );
    wrap(<ConnectionCheckCard wid={WID} />);
    fireEvent.click(screen.getByRole("button", { name: /Test connection/ }));
    await screen.findByText("Protected resource metadata");
    await waitFor(() => expect(screen.getByText(/initialize HTTP 502/)).toBeInTheDocument());
    expect(screen.getByLabelText("passed")).toBeInTheDocument();
    expect(screen.getByLabelText("failed")).toBeInTheDocument();
  });
});
