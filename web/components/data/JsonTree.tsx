import React, { useState } from "react";
import { ChevronDown, ChevronRight, Copy } from "lucide-react";
import { Badge, Button } from "@/components/ui/primitives";

const ARRAY_CHUNK = 50;
const STRING_PREVIEW_LIMIT = 240;

interface JsonTreeNodeProps {
  name: string;
  path: string;
  value: unknown;
  depth: number;
  initialExpandDepth?: number;
  maxDepth?: number;
  searchTerm?: string;
  formatNumbers?: boolean;
  onCopy?: (label: string, text: string) => void;
}

function matchesSearch(name: string, value: unknown, term: string): boolean {
  if (!term) return true;
  const q = term.toLowerCase();
  if (name.toLowerCase().includes(q)) return true;
  if (value === null || typeof value !== "object") {
    return String(value).toLowerCase().includes(q);
  }
  return true;
}

function JsonTreeNode({
  name,
  path,
  value,
  depth,
  initialExpandDepth = 2,
  maxDepth = 10,
  searchTerm = "",
  formatNumbers = false,
  onCopy,
}: JsonTreeNodeProps) {
  const isArray = Array.isArray(value);
  const isObject = value !== null && typeof value === "object" && !isArray;
  const isContainer = isArray || isObject;

  const [expanded, setExpanded] = useState(depth < initialExpandDepth);
  const [arrayLimit, setArrayLimit] = useState(ARRAY_CHUNK);
  const [stringExpanded, setStringExpanded] = useState(false);

  if (!matchesSearch(name, value, searchTerm)) {
    return null;
  }

  const copyText = (label: string, text: string) => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      void navigator.clipboard.writeText(text);
    }
    onCopy?.(label, text);
  };

  if (!isContainer) {
    let rendered: React.ReactNode;
    let typeBadge: string = typeof value;
    if (value === null) {
      typeBadge = "null";
      rendered = <span className="font-mono text-xs text-[hsl(var(--muted-foreground))]">null</span>;
    } else if (value === undefined) {
      typeBadge = "undefined";
      rendered = <span className="font-mono text-xs text-[hsl(var(--muted-foreground))]">undefined</span>;
    } else if (typeof value === "boolean") {
      rendered = (
        <span className="font-mono text-xs font-semibold text-amber-600 dark:text-amber-400">
          {String(value)}
        </span>
      );
    } else if (typeof value === "number") {
      rendered = (
        <span className="font-mono text-xs text-sky-700 dark:text-sky-300">
          {formatNumbers ? value.toLocaleString() : String(value)}
        </span>
      );
    } else {
      const s = String(value);
      const isLong = s.length > STRING_PREVIEW_LIMIT;
      const shown = isLong && !stringExpanded ? `${s.slice(0, STRING_PREVIEW_LIMIT)}…` : s;
      rendered = (
        <span className="break-all font-mono text-xs text-emerald-700 dark:text-emerald-300">
          &quot;{shown}&quot;
          {isLong && (
            <button
              type="button"
              className="ml-1.5 text-[11px] underline text-[hsl(var(--primary))]"
              onClick={() => setStringExpanded((v) => !v)}
            >
              {stringExpanded ? "Collapse" : `Expand (${s.length.toLocaleString()} chars)`}
            </button>
          )}
        </span>
      );
    }

    return (
      <div className="group flex items-start justify-between gap-2 rounded px-1.5 py-0.5 hover:bg-[hsl(var(--muted))]/40">
        <div className="flex min-w-0 flex-wrap items-baseline gap-1.5">
          <span className="font-mono text-xs font-medium text-[hsl(var(--foreground))]">
            {name}
          </span>
          <span className="text-[10px] text-[hsl(var(--muted-foreground))]">{typeBadge}</span>
          {rendered}
        </div>
        <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
          <button
            type="button"
            className="rounded p-0.5 text-[10px] text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--muted))]"
            title={`Copy path: ${path}`}
            aria-label={`Copy path ${path}`}
            onClick={() => copyText("Path copied", path)}
          >
            path
          </button>
          <button
            type="button"
            className="rounded p-0.5 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--muted))]"
            title="Copy value"
            aria-label={`Copy value for ${path}`}
            onClick={() => copyText("Value copied", value === null ? "null" : String(value))}
          >
            <Copy className="h-3 w-3" />
          </button>
        </div>
      </div>
    );
  }

  const entries: Array<[string, unknown]> = isArray
    ? (value as unknown[]).map((v, i) => [`[${i}]`, v])
    : Object.entries(value as Record<string, unknown>);
  const totalCount = entries.length;
  const visibleEntries = isArray ? entries.slice(0, arrayLimit) : entries;
  const overMaxDepth = depth >= maxDepth;

  return (
    <div className="my-0.5">
      <div className="group flex items-center justify-between gap-2 rounded px-1.5 py-0.5 hover:bg-[hsl(var(--muted))]/40">
        <button
          type="button"
          className="flex items-center gap-1 text-left"
          aria-expanded={expanded}
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? (
            <ChevronDown className="h-3.5 w-3.5 text-[hsl(var(--muted-foreground))]" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-[hsl(var(--muted-foreground))]" />
          )}
          <span className="font-mono text-xs font-semibold">{name}</span>
          <Badge tone="neutral">
            {isArray
              ? `[${totalCount.toLocaleString()} ${totalCount === 1 ? "item" : "items"}]`
              : `{${totalCount} ${totalCount === 1 ? "key" : "keys"}}`}
          </Badge>
        </button>
        <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
          <button
            type="button"
            className="rounded p-0.5 text-[10px] text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--muted))]"
            aria-label={`Copy path ${path}`}
            onClick={() => copyText("Path copied", path)}
          >
            path
          </button>
          <button
            type="button"
            className="rounded p-0.5 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--muted))]"
            aria-label={`Copy JSON for ${path}`}
            onClick={() => copyText("JSON copied", JSON.stringify(value, null, 2))}
          >
            <Copy className="h-3 w-3" />
          </button>
        </div>
      </div>

      {expanded && (
        <div className="ml-3 border-l border-[hsl(var(--border))] pl-2.5">
          {overMaxDepth ? (
            <div className="py-1 text-xs text-[hsl(var(--muted-foreground))]">
              Max render depth ({maxDepth}) reached. Use Copy JSON to inspect deeper levels.
            </div>
          ) : totalCount === 0 ? (
            <div className="py-0.5 font-mono text-xs text-[hsl(var(--muted-foreground))]">
              {isArray ? "[]" : "{}"}
            </div>
          ) : (
            <>
              {visibleEntries.map(([childKey, childVal]) => {
                const childPath = isArray
                  ? `${path}${childKey}`
                  : path
                    ? `${path}.${childKey}`
                    : childKey;
                return (
                  <JsonTreeNode
                    key={childPath}
                    name={childKey}
                    path={childPath}
                    value={childVal}
                    depth={depth + 1}
                    initialExpandDepth={initialExpandDepth}
                    maxDepth={maxDepth}
                    searchTerm={searchTerm}
                    formatNumbers={formatNumbers}
                    onCopy={onCopy}
                  />
                );
              })}
              {isArray && arrayLimit < totalCount && (
                <div className="py-1">
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => setArrayLimit((n) => n + ARRAY_CHUNK)}
                  >
                    Show next {Math.min(ARRAY_CHUNK, totalCount - arrayLimit)} of{" "}
                    {(totalCount - arrayLimit).toLocaleString()} remaining items
                  </Button>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

export interface JsonTreeProps {
  data: unknown;
  rootName?: string;
  initialExpandDepth?: number;
  maxDepth?: number;
  searchTerm?: string;
  formatNumbers?: boolean;
  onCopy?: (label: string, text: string) => void;
}

export function JsonTree({
  data,
  rootName = "data",
  initialExpandDepth = 2,
  maxDepth = 10,
  searchTerm = "",
  formatNumbers = false,
  onCopy,
}: JsonTreeProps) {
  return (
    <div className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-2.5 text-sm">
      <JsonTreeNode
        name={rootName}
        path={rootName}
        value={data}
        depth={0}
        initialExpandDepth={initialExpandDepth}
        maxDepth={maxDepth}
        searchTerm={searchTerm}
        formatNumbers={formatNumbers}
        onCopy={onCopy}
      />
    </div>
  );
}
