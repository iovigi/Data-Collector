import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import DataExplorerPage from "@/app/w/[workspaceId]/collections/[collectionId]/data/page";

vi.mock("@/components/layout/AppShell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <main>{children}</main>,
}));
vi.mock("@/components/providers", () => ({ useToast: () => ({ toast: vi.fn() }) }));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("pages through full-text separately from structured results and exposes the edit action", async () => {
  const pathname = "/w/example/collections/logs/data";
  const first = { record: { id: "first", data: { title: "First result" }, version: 1 }, highlights: [] };
  const second = { record: { id: "second", data: { title: "Second result" }, version: 1 }, highlights: [] };
  const cursors: Array<string | null> = [];
  const index = { enabled: true, ready: true, state: "ready", coverage: "complete", indexed_records: 2 };

  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    let body: unknown;
    if (url.endsWith("/capabilities")) {
      body = { features: { can_write_records: true } };
    } else if (url.endsWith("/search/status")) {
      body = index;
    } else if (url.endsWith("/records/fulltext")) {
      const { cursor } = JSON.parse(String(init?.body));
      cursors.push(cursor);
      body = cursor
        ? { items: [second], has_more: false, next_cursor: null, index_status: index }
        : { items: [first], has_more: true, next_cursor: "page-two", index_status: index };
    } else if (url.endsWith("/records/search")) {
      body = { items: [{ id: "structured", data: { title: "Structured result" }, version: 1 }] };
    } else if (url.endsWith("/record-count")) {
      body = {};
    } else {
      body = { slug: "logs", schema_json: { properties: { title: { type: "string" } } } };
    }
    return new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } });
  });

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[pathname]}>
        <Routes>
          <Route path="/w/:workspaceId/collections/:collectionId/data" element={<DataExplorerPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );

  await screen.findByText("Structured result");
  fireEvent.click(screen.getByRole("button", { name: "Full-text Search" }));
  expect(screen.queryByText("Structured result")).not.toBeInTheDocument();
  fireEvent.change(await screen.findByRole("searchbox"), { target: { value: "result" } });
  fireEvent.click(screen.getByRole("button", { name: "Search" }));
  await screen.findByText("First result");

  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  await screen.findByText("Second result");
  expect(cursors.slice(0, 2)).toEqual([null, "page-two"]);

  fireEvent.click(screen.getByRole("button", { name: "Previous" }));
  await screen.findByText("First result");
  expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/records/search"))).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  expect(screen.getByRole("dialog", { name: "Edit record" })).toBeInTheDocument();
  expect(screen.getByLabelText("Record JSON data")).toHaveValue('{\n  "title": "First result"\n}');
});
