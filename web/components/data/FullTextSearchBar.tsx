import React from "react";
import { RefreshCw, Search, X } from "lucide-react";
import type { FulltextSearchResponse, SearchStatusResponse } from "@/lib/api/types";
import { Badge, Button, Input } from "@/components/ui/primitives";

interface FullTextSearchBarProps {
  status?: SearchStatusResponse;
  resultStatus?: FulltextSearchResponse["index_status"];
  statusLoading: boolean;
  statusError: boolean;
  onRefreshStatus: () => void;
  text: string;
  onTextChange: (text: string) => void;
  onSearch: (query: string) => void;
  onClear: () => void;
  isSearching: boolean;
}

export function FullTextSearchBar({
  status,
  resultStatus,
  statusLoading,
  statusError,
  onRefreshStatus,
  text,
  onTextChange,
  onSearch,
  onClear,
  isSearching,
}: FullTextSearchBarProps) {
  const ready = status?.ready === true;
  const coverage = resultStatus ?? status;
  const partial = coverage?.coverage === "partial";
  const statusText = statusLoading
    ? "Checking search availability…"
    : statusError
      ? "Search status could not be loaded."
      : !status?.enabled
        ? "Full-text search is disabled for this deployment."
        : status.state === "not_indexed"
          ? "This collection is waiting for its first indexing run."
          : "The search index is temporarily unavailable.";

  return (
    <div className="space-y-3">
      {ready && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (text.trim() && !isSearching) onSearch(text.trim());
          }}
          className="flex flex-wrap items-center gap-2"
        >
          <Input
            type="search"
            value={text}
            maxLength={256}
            onChange={(e) => onTextChange(e.target.value)}
            placeholder={'Search text or an exact phrase like "payment failed"'}
            aria-label="Full-text search query"
            className="min-w-0 basis-full sm:flex-1"
          />
          <Button type="submit" disabled={isSearching || !text.trim()}>
            <Search className="h-3.5 w-3.5" aria-hidden="true" />
            {isSearching ? "Searching…" : "Search"}
          </Button>
          {text && (
            <Button variant="ghost" type="button" onClick={onClear}>
              <X className="h-3.5 w-3.5" aria-hidden="true" />
              Clear
            </Button>
          )}
        </form>
      )}
      <div className="flex flex-wrap items-center gap-2 text-xs text-[hsl(var(--muted-foreground))]">
        <div className="flex flex-1 flex-wrap items-center gap-x-2 gap-y-1" role="status">
          {ready && coverage ? (
            <>
              <Badge tone={partial ? "warning" : "neutral"}>
                {partial ? "Partial index" : "Indexed snapshot"}
              </Badge>
              <span>{coverage.indexed_records.toLocaleString()} records indexed</span>
              {coverage.as_of && <span>Updated {new Date(coverage.as_of).toLocaleString()}</span>}
              {!status?.incremental_sync_supported && <span>Refreshed by manual indexing</span>}
            </>
          ) : (
            <span>{statusText} {!statusLoading && "Structured Filters are available."}</span>
          )}
        </div>
        {!statusLoading && (
          <Button size="sm" variant="ghost" type="button" onClick={onRefreshStatus}>
            <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            Refresh status
          </Button>
        )}
      </div>
    </div>
  );
}
