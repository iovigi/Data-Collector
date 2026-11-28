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

  const walk = (obj: unknown, prefix: string, depth: number, source: "schema" | "sampled") => {
    if (seen.size >= MAX_DISCOVERED_PATHS || depth > MAX_SAMPLE_DEPTH) return;
    if (!obj || typeof obj !== "object" || Array.isArray(obj)) return;
    for (const [key, val] of Object.entries(obj as Record<string, unknown>)) {
      if (seen.size >= MAX_DISCOVERED_PATHS) break;
      const p = prefix ? `${prefix}.${key}` : key;
      if (!seen.has(p)) seen.set(p, source);
      if (val && typeof val === "object" && !Array.isArray(val)) {
        walk(val, p, depth + 1, source);
      }
    }
  };

  for (const key of Object.keys(schemaProperties)) {
    if (seen.size >= MAX_DISCOVERED_PATHS) break;
    seen.set(key, "schema");
    const prop = schemaProperties[key] as { properties?: Record<string, unknown> } | undefined;
    if (prop?.properties) {
      walk(prop.properties, key, 2, "schema");
    }
  }

  for (const rec of records.slice(0, MAX_SAMPLED_DOCS)) {
    walk(rec.data, "", 1, "sampled");
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

  const toggle = (path: string) => {
    if (selectedSet.has(path)) {
      onChange(visibleColumns.filter((p) => p !== path));
    } else {
      onChange([...visibleColumns, path]);
    }
  };

  return (
    <div className="relative">
      <Button size="sm" variant="secondary" onClick={() => setOpen((v) => !v)}>
        <Columns className="h-3.5 w-3.5" />
        Columns ({visibleColumns.length})
      </Button>
      {open && (
        <div className="absolute right-0 z-30 mt-1 max-h-72 w-72 overflow-y-auto rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-2.5 shadow-lg">
          <div className="mb-2 flex items-center justify-between text-xs font-semibold">
            <span>Visible Columns (local)</span>
            <button
              type="button"
              className="text-[hsl(var(--primary))] underline"
              onClick={() => setOpen(false)}
            >
              Done
            </button>
          </div>
          {availablePaths.length === 0 ? (
            <div className="text-xs text-[hsl(var(--muted-foreground))]">No fields discovered</div>
          ) : (
            <div className="space-y-1">
              {availablePaths.map(({ path, source }) => (
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
