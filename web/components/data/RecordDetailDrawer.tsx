import React, { useEffect, useState } from "react";
import { X } from "lucide-react";
import type { RecordItem } from "@/lib/api/types";
import { Badge, Button, CopyButton, Input } from "@/components/ui/primitives";
import { JsonTree } from "./JsonTree";

interface RecordDetailDrawerProps {
  record: RecordItem | null;
  onClose: () => void;
  canEdit?: boolean;
  onEdit?: (record: RecordItem) => void;
  onCopyToast?: (msg: string) => void;
}

export function RecordDetailDrawer({
  record,
  onClose,
  canEdit = false,
  onEdit,
  onCopyToast,
}: RecordDetailDrawerProps) {
  const [viewMode, setViewMode] = useState<"tree" | "raw">("tree");
  const [treeSearch, setTreeSearch] = useState("");
  const [formatNumbers, setFormatNumbers] = useState(false);

  useEffect(() => {
    if (!record) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [record, onClose]);

  if (!record) return null;

  const rawJson = JSON.stringify(record.data, null, 2);

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-label={`Inspect record ${record.id}`}
    >
      <div className="flex h-full w-full max-w-2xl flex-col border-l border-[hsl(var(--border))] bg-[hsl(var(--card))] shadow-xl">
        <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-4 py-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="font-semibold">Record Inspector</span>
              <Badge>v{record.version}</Badge>
            </div>
            <div className="mt-0.5 font-mono text-xs text-[hsl(var(--muted-foreground))]">
              {record.id}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {canEdit && onEdit && (
              <Button size="sm" variant="secondary" onClick={() => onEdit(record)}>
                Edit JSON
              </Button>
            )}
            <Button size="sm" variant="ghost" aria-label="Close inspector" onClick={onClose}>
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2 border-b border-[hsl(var(--border))] bg-[hsl(var(--muted))]/30 px-4 py-2.5 text-xs">
          <div>
            <span className="text-[hsl(var(--muted-foreground))]">Created: </span>
            <span className="font-mono">{record.created_at}</span>
          </div>
          <div>
            <span className="text-[hsl(var(--muted-foreground))]">Updated: </span>
            <span className="font-mono">{record.updated_at}</span>
          </div>
          <div>
            <span className="text-[hsl(var(--muted-foreground))]">Created by: </span>
            <span className="font-mono">{record.created_by}</span>
          </div>
          <div>
            <span className="text-[hsl(var(--muted-foreground))]">Source: </span>
            <span className="font-mono">{String(record.source?.type ?? "api")}</span>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[hsl(var(--border))] px-4 py-2">
          <div className="flex gap-1.5">
            <Button
              size="sm"
              variant={viewMode === "tree" ? "primary" : "secondary"}
              onClick={() => setViewMode("tree")}
            >
              Tree View
            </Button>
            <Button
              size="sm"
              variant={viewMode === "raw" ? "primary" : "secondary"}
              onClick={() => setViewMode("raw")}
            >
              Raw JSON
            </Button>
          </div>
          <div className="flex items-center gap-2">
            {viewMode === "tree" && (
              <>
                <Input
                  value={treeSearch}
                  onChange={(e) => setTreeSearch(e.target.value)}
                  placeholder="Find in record..."
                  aria-label="Filter fields in loaded record"
                  className="h-8 w-40 text-xs"
                />
                <label className="flex items-center gap-1 text-xs text-[hsl(var(--muted-foreground))]">
                  <input
                    type="checkbox"
                    checked={formatNumbers}
                    onChange={(e) => setFormatNumbers(e.target.checked)}
                  />
                  Locale nums
                </label>
              </>
            )}
            <CopyButton text={rawJson} label="Copy JSON" />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {viewMode === "tree" ? (
            <JsonTree
              data={record.data}
              rootName="data"
              initialExpandDepth={2}
              searchTerm={treeSearch}
              formatNumbers={formatNumbers}
              onCopy={(label) => onCopyToast?.(label)}
            />
          ) : (
            <pre className="overflow-x-auto rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3 font-mono text-xs">
              {rawJson}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}
