import React from "react";
import { Badge } from "@/components/ui/primitives";

export function getNestedValue(obj: Record<string, unknown>, path: string): unknown {
  if (!path.includes(".")) return obj[path];
  let cur: unknown = obj;
  for (const part of path.split(".")) {
    if (cur === null || cur === undefined || typeof cur !== "object" || Array.isArray(cur)) {
      return undefined;
    }
    cur = (cur as Record<string, unknown>)[part];
  }
  return cur;
}

export function NestedValuePreview({ value }: { value: unknown }) {
  if (value === undefined) {
    return <span className="text-xs text-[hsl(var(--muted-foreground))]">missing</span>;
  }
  if (value === null) {
    return <Badge tone="neutral">null</Badge>;
  }
  if (typeof value === "boolean") {
    return <Badge tone={value ? "success" : "neutral"}>{String(value)}</Badge>;
  }
  if (typeof value === "number") {
    return <span className="font-mono text-xs">{value.toLocaleString()}</span>;
  }
  if (Array.isArray(value)) {
    return (
      <span className="inline-flex items-center gap-1 font-mono text-xs text-[hsl(var(--muted-foreground))]">
        <Badge tone="neutral">[{value.length.toLocaleString()} items]</Badge>
      </span>
    );
  }
  if (typeof value === "object") {
    const keys = Object.keys(value as Record<string, unknown>);
    return (
      <Badge tone="neutral">{`{${keys.length} ${keys.length === 1 ? "key" : "keys"}}`}</Badge>
    );
  }
  const str = String(value);
  return (
    <span className="block max-w-[240px] truncate font-mono text-xs" title={str.slice(0, 500)}>
      {str}
    </span>
  );
}
