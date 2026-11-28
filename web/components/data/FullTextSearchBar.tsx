import React, { useState } from "react";
import { Search, X } from "lucide-react";
import type { SearchStatusResponse } from "@/lib/api/types";
import { Badge, Button, Input } from "@/components/ui/primitives";

export function IndexStatusBadge({ status }: { status?: SearchStatusResponse }) {
  if (!status) return null;
  if (!status.enabled || !status.ready) {
    return (
      <span title="External full-text search is disabled by operator config">
        <Badge tone="neutral">
          Full-text: {status.enabled ? status.state : "disabled"}
        </Badge>
      </span>
    );
  }
  const tone = status.coverage === "complete" ? "success" : "warning";
  return (
    <span
      title={`Backend: ${status.backend}, indexed: ${status.indexed_records.toLocaleString()}, as of ${status.as_of ?? "n/a"}`}
    >
      <Badge tone={tone}>
        Full-text: {status.coverage} ({status.indexed_records.toLocaleString()} indexed)
      </Badge>
    </span>
  );
}

interface FullTextSearchBarProps {
  status?: SearchStatusResponse;
  onSearch: (query: string) => void;
  onClear: () => void;
  isSearching?: boolean;
}

export function FullTextSearchBar({
  status,
  onSearch,
  onClear,
  isSearching = false,
}: FullTextSearchBarProps) {
  const [text, setText] = useState("");
  const ready = Boolean(status?.enabled && status?.ready);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!ready || !text.trim()) return;
    onSearch(text.trim());
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs text-[hsl(var(--muted-foreground))]">
          External full-text search (isolated index, no MongoDB collection scans)
        </div>
        <IndexStatusBadge status={status} />
      </div>
      {!ready ? (
        <div className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/30 px-3 py-2 text-xs text-[hsl(var(--muted-foreground))]">
          External full-text search is currently disabled or not yet indexed for this collection.
          Use <strong>Structured Filters</strong> for index-backed queries.
        </div>
      ) : (
        <form onSubmit={submit} className="flex flex-wrap items-center gap-2">
          <Input
            value={text}
            maxLength={256}
            onChange={(e) => setText(e.target.value)}
            placeholder='Search text across nested fields (e.g. "payment failed")'
            aria-label="Full-text search query"
            className="min-w-[260px] flex-1"
          />
          <Button size="sm" type="submit" disabled={isSearching || !text.trim()}>
            <Search className="h-3.5 w-3.5" />
            {isSearching ? "Searching..." : "Full-text Search"}
          </Button>
          {text && (
            <Button
              size="sm"
              variant="secondary"
              type="button"
              onClick={() => {
                setText("");
                onClear();
              }}
            >
              <X className="h-3.5 w-3.5" />
              Clear
            </Button>
          )}
        </form>
      )}
    </div>
  );
}
