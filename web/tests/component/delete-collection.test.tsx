import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DeleteCollectionDialog } from "@/components/collections/DeleteCollectionDialog";

const CID = "6b063b57e8c6ea6c1abb2c7d";

const PREP = {
  collection_id: CID,
  workspace_id: "6b063983504ba8645c1c5beb",
  project_id: "6b063983504ba8645c1c5bee",
  slug: "leads-business",
  status: "active",
  records: { active: 1200, trashed: 34, total: 1234 },
  saved_queries: { count: 2, items: [] },
  active_jobs: { count: 0, items: [] },
  api_keys_restricted_to_collection: 1,
  confirmation_token: "tok.sig",
  expires_in_seconds: 300,
  correlation_id: "cdel_x",
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("DeleteCollectionDialog", () => {
  it("prepares, shows counts, and requires the exact slug before deleting", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(PREP))
      .mockResolvedValueOnce(
        jsonResponse({ collection_id: CID, slug: "leads-business", deleted: true, records_deleted: 1234 })
      );
    const onDeleted = vi.fn();
    render(
      <DeleteCollectionDialog open onClose={() => {}} collectionId={CID} onDeleted={onDeleted} />
    );

    await screen.findByTestId("count-records");
    expect(fetchMock.mock.calls[0]![0]).toBe(`/api/backend/collections/${CID}/prepare-delete`);
    expect(fetchMock.mock.calls[0]![1]?.method).toBe("POST");
    expect(screen.getByTestId("count-records").textContent).toContain("1,234");
    expect(screen.getByTestId("count-records").textContent).toContain("34");
    expect(screen.getByTestId("count-saved-queries").textContent).toContain("2");

    const del = screen.getByRole("button", { name: "Delete collection" });
    expect(del).toBeDisabled();
    const input = screen.getByLabelText(/to confirm/);
    fireEvent.change(input, { target: { value: "leads-business-v2" } });
    expect(del).toBeDisabled();
    fireEvent.change(input, { target: { value: "leads-business" } });
    expect(del).toBeEnabled();

    fireEvent.click(del);
    await waitFor(() => expect(onDeleted).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[1]!;
    expect(url).toBe(`/api/backend/collections/${CID}`);
    expect(init?.method).toBe("DELETE");
    expect(JSON.parse(String(init?.body))).toEqual({
      confirmation_token: "tok.sig",
      confirm_slug: "leads-business",
    });
  });

  it("shows the server error when prepare is forbidden", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse({ error: { code: "FORBIDDEN", message: "Missing required scope", request_id: "r" } }, 403)
    );
    render(<DeleteCollectionDialog open onClose={() => {}} collectionId={CID} onDeleted={() => {}} />);
    await screen.findByText("Missing required scope");
    expect(screen.getByRole("button", { name: "Delete collection" })).toBeDisabled();
  });
});

