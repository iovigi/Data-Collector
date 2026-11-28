import React, { useMemo, useState } from "react";
import { Columns } from "lucide-react";
import type { RecordItem } from "@/lib/api/types";
import { Button } from "@/components/ui/primitives";

const MAX_DISCOVERED_PATHS = 200;
const MAX_SAMPLED_DOCS = 100;
const MAX_SAMPLE_DEPTH = 6;

export function discoverRecordPaths(
  schemaProperties: Record<string, unknown>,
  records: RecordItem[]
): Array<{ path: string; source: "schema" | "sampled" }> {
  const seen = new Map<string, "schema" | "sampled">();

  function walk(
    properties: Record<string, unknown>,
    prefix: string,
    depth: number,
    source: "schema" | "sampled"
  ) {
    if (depth > MAX_SAMPLE_DEPTH) return;
    for (const [key, value] of Object.entries(properties)) {
      if (seen.size >= MAX_DISCOVERED_PATHS) break;
      const segment = key.replaceAll("\\", "\\\\").replaceAll(".", "\\.");
      const path = prefix ? `${prefix}.${segment}` : segment;
      if (!seen.has(path)) seen.set(path, source);
      if (!value || typeof value !== "object" || Array.isArray(value)) continue;
      const object = value as Record<string, unknown>;
      if (source === "sampled") {
        walk(object, path, depth + 1, source);
      } else if (object.properties && typeof object.properties === "object" && !Array.isArray(object.properties)) {
        walk(object.properties as Record<string, unknown>, path, depth + 1, source);
      }
    }
  }

  walk(schemaProperties, "", 1, "schema");
  for (const record of records.slice(0, MAX_SAMPLED_DOCS)) {
    walk(record.data, "", 1, "sampled");
  }

  return Array.from(seen.entries()).map(([path, source]) => ({ path, source }));
}

interface FieldVisibilityPickerProps {
  availablePaths: Array<{ path: string; source: "schema" | "sampled" }>;
  visibleColumns: string[];
  onChange: (next: string[]) => void;
}

export function FieldVisibilityPicker({
  availablePaths,
  visibleColumns,
  onChange,
}: FieldVisibilityPickerProps) {
  const [open, setOpen] = useState(false);

  const selectedSet = useMemo(() => new Set(visibleColumns), [visibleColumns]);
  const choices = [
    ...availablePaths,
    ...visibleColumns
      .filter((path) => !availablePaths.some((item) => item.path === path))
      .map((path) => ({ path, source: "selected" })),
  ];

  const toggle = (path: string) => {
    if (selectedSet.has(path)) {
      onChange(visibleColumns.filter((p) => p !== path));
    } else {
      onChange([...visibleColumns, path]);
    }
  };

  return (
    <div className="relative">
      <Button size="sm" variant="secondary" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <Columns className="h-3.5 w-3.5" />
        Columns ({visibleColumns.length})
      </Button>
      {open && (
        <div className="absolute right-0 z-30 mt-1 max-h-72 w-60 sm:w-72 overflow-y-auto rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-2.5 shadow-lg">
          <div className="mb-2 flex items-center justify-between text-xs font-semibold">
            <span>Visible columns</span>
            <button
              type="button"
              className="text-[hsl(var(--primary))] underline"
              onClick={() => setOpen(false)}
            >
              Done
            </button>
          </div>
          {choices.length === 0 ? (
            <div className="text-xs text-[hsl(var(--muted-foreground))]">No fields discovered</div>
          ) : (
            <div className="space-y-1">
              {choices.map(({ path, source }) => (
                <label
                  key={path}
                  className="flex cursor-pointer items-center justify-between gap-2 rounded px-1.5 py-1 text-xs hover:bg-[hsl(var(--muted))]/40"
                >
                  <span className="flex items-center gap-1.5 truncate font-mono">
                    <input
                      type="checkbox"
                      checked={selectedSet.has(path)}
                      onChange={() => toggle(path)}
                    />
                    <span className="truncate">{path}</span>
                  </span>
                  <span className="shrink-0 text-[10px] text-[hsl(var(--muted-foreground))]">
                    {source}
                  </span>
                </label>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
