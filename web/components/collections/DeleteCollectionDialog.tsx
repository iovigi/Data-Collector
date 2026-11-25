"use client";

import React, { useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { apiFetch } from "@/lib/api/client";
import type {
  DeleteCollectionResponse,
  PrepareDeleteCollectionResponse,
} from "@/lib/api/types";
import { Button, ErrorState, Input, Modal } from "@/components/ui/primitives";

/**
 * Two-step collection delete: on open it calls prepare-delete, shows what will be removed,
 * and only enables the destructive button once the user has typed the exact slug.
 */
export function DeleteCollectionDialog({
  open,
  onClose,
  collectionId,
  onDeleted,
}: {
  open: boolean;
  onClose: () => void;
  collectionId: string;
  onDeleted: (res: DeleteCollectionResponse) => void;
}) {
  const [prep, setPrep] = useState<PrepareDeleteCollectionResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [typed, setTyped] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setPrep(null);
    setError(null);
    setTyped("");
    setLoading(true);
    apiFetch<PrepareDeleteCollectionResponse>(`/collections/${collectionId}/prepare-delete`, {
      method: "POST",
    })
      .then((res) => {
        if (!cancelled) setPrep(res);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, collectionId]);

  async function handleDelete() {
    if (!prep) return;
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch<DeleteCollectionResponse>(`/collections/${collectionId}`, {
        method: "DELETE",
        body: { confirmation_token: prep.confirmation_token, confirm_slug: typed },
      });
      onDeleted(res);
    } catch (err) {
      setError(err as Error);
    } finally {
      setLoading(false);
    }
  }

  const slugMatches = prep !== null && typed === prep.slug;

  return (
    <Modal open={open} onClose={onClose} title="Delete collection">
      {loading && !prep && !error && (
        <p className="text-sm text-[hsl(var(--muted-foreground))]">Checking what will be removed…</p>
      )}
      {error && <ErrorState error={error} />}
      {prep && (
        <div className="space-y-4 text-sm">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-[hsl(var(--destructive))]" />
            <p>
              This permanently deletes <strong className="font-mono">{prep.slug}</strong> and
              everything in it. It cannot be undone or restored from trash.
            </p>
          </div>
          <ul className="space-y-1 rounded-md border border-[hsl(var(--border))] p-3" aria-label="What will be removed">
            <li data-testid="count-records">
              <strong>{prep.records.total.toLocaleString()}</strong> records (
              {prep.records.active.toLocaleString()} active, {prep.records.trashed.toLocaleString()} in
              trash)
            </li>
            <li data-testid="count-saved-queries">
              <strong>{prep.saved_queries.count}</strong> saved{" "}
              {prep.saved_queries.count === 1 ? "query" : "queries"}
            </li>
            <li data-testid="count-jobs">
              <strong>{prep.active_jobs.count}</strong> queued/running{" "}
              {prep.active_jobs.count === 1 ? "job" : "jobs"} will be cancelled
            </li>
            <li data-testid="count-keys">
              <strong>{prep.api_keys_restricted_to_collection}</strong> API{" "}
              {prep.api_keys_restricted_to_collection === 1 ? "key loses" : "keys lose"} access to
              this collection
            </li>
          </ul>
          <div>
            <label htmlFor="confirm-slug" className="mb-1 block font-medium">
              Type <span className="font-mono">{prep.slug}</span> to confirm
            </label>
            <Input
              id="confirm-slug"
              autoComplete="off"
              spellCheck={false}
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
            />
          </div>
          <p className="text-xs text-[hsl(var(--muted-foreground))]">
            The confirmation expires in {Math.round(prep.expires_in_seconds / 60)} minutes.
          </p>
        </div>
      )}
      <div className="mt-6 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose} disabled={loading && prep !== null}>
          Cancel
        </Button>
        <Button variant="danger" onClick={handleDelete} disabled={!slugMatches || loading}>
          {loading && prep ? "Deleting…" : "Delete collection"}
        </Button>
      </div>
    </Modal>
  );
}
