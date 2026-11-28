import React from "react";
import { RefreshCw } from "lucide-react";
import type { CountBucket } from "@/lib/api/types";
import { Badge, Button } from "@/components/ui/primitives";

interface CountBadgeProps {
  bucket?: CountBucket | null;
  label?: string;
  onRefresh?: () => void;
  refreshing?: boolean;
  compact?: boolean;
}

function formatAge(ageSeconds: number | null | undefined): string {
  if (ageSeconds === null || ageSeconds === undefined) return "";
  if (ageSeconds < 60) return `${ageSeconds}s ago`;
  if (ageSeconds < 3600) return `${Math.floor(ageSeconds / 60)}m ago`;
  return `${Math.floor(ageSeconds / 3600)}h ago`;
}

export function CountBadge({
  bucket,
  label = "Records",
  onRefresh,
  refreshing = false,
  compact = false,
}: CountBadgeProps) {
  if (!bucket || bucket.accuracy === "pending") {
    return (
      <span
        className="inline-flex items-center gap-1.5"
        aria-label={`${label}: count pending`}
        title={bucket?.reason ?? "Count is pending cached or background computation"}
      >
        <Badge tone="warning">{compact ? "Pending" : `${label}: Pending`}</Badge>
        {onRefresh && (
          <Button
            size="sm"
            variant="ghost"
            aria-label={`Refresh ${label.toLowerCase()} count`}
            disabled={refreshing}
            onClick={onRefresh}
          >
            <RefreshCw className={`h-3 w-3 ${refreshing ? "animate-spin" : ""}`} />
          </Button>
        )}
      </span>
    );
  }

  if (bucket.accuracy === "unavailable" || bucket.value === null) {
    return (
      <span
        className="inline-flex items-center gap-1.5"
        aria-label={`${label}: count unavailable`}
        title={bucket.reason ?? "Count unavailable for current index plan"}
      >
        <Badge tone="neutral">{compact ? "Unavailable" : `${label}: Unavailable`}</Badge>
        {onRefresh && (
          <Button
            size="sm"
            variant="ghost"
            aria-label={`Retry ${label.toLowerCase()} count`}
            disabled={refreshing}
            onClick={onRefresh}
          >
            <RefreshCw className={`h-3 w-3 ${refreshing ? "animate-spin" : ""}`} />
          </Button>
        )}
      </span>
    );
  }

  const formatted = bucket.value.toLocaleString();
  const ageText = formatAge(bucket.age_seconds);
  const accuracyLabel =
    bucket.accuracy === "exact_as_of"
      ? "exact"
      : bucket.accuracy === "indexed"
        ? "indexed"
        : "cached";
  const tooltip = `${label}: ${formatted} (${accuracyLabel}${bucket.as_of ? `, as of ${bucket.as_of}` : ""})`;

  return (
    <span
      className="inline-flex items-center gap-1.5"
      aria-label={tooltip}
      title={tooltip}
    >
      <Badge tone="primary">
        {compact ? formatted : `${label}: ${formatted}`}
        <span className="ml-1 opacity-75">
          ({accuracyLabel}
          {ageText ? ` · ${ageText}` : ""})
        </span>
      </Badge>
      {onRefresh && (
        <Button
          size="sm"
          variant="ghost"
          aria-label={`Refresh ${label.toLowerCase()} count`}
          disabled={refreshing}
          onClick={onRefresh}
        >
          <RefreshCw className={`h-3 w-3 ${refreshing ? "animate-spin" : ""}`} />
        </Button>
      )}
    </span>
  );
}
