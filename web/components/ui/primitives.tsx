import React, { useState } from "react";
import { AlertTriangle, Check, Copy, Lock, ShieldAlert, X } from "lucide-react";
import { ApiError } from "@/lib/api/errors";

export function Button({
  variant = "primary",
  size = "md",
  className = "",
  children,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  size?: "sm" | "md";
}) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[hsl(var(--primary))] disabled:opacity-50 disabled:pointer-events-none cursor-pointer";
  const sizes = {
    sm: "h-8 px-3 text-xs",
    md: "h-9 px-4 text-sm",
  };
  const variants = {
    primary: "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] hover:opacity-90",
    secondary:
      "border border-[hsl(var(--border))] bg-[hsl(var(--surface-elevated))] hover:bg-[hsl(var(--muted))]",
    danger: "bg-[hsl(var(--destructive))] text-[hsl(var(--destructive-foreground))] hover:opacity-90",
    ghost: "hover:bg-[hsl(var(--muted))]",
  };
  return (
    <button className={`${base} ${sizes[size]} ${variants[variant]} ${className}`} {...props}>
      {children}
    </button>
  );
}

export function Input({
  className = "",
  ...props
}: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={`h-9 w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary))] ${className}`}
      {...props}
    />
  );
}

export function Select({
  className = "",
  children,
  ...props
}: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={`h-9 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary))] ${className}`}
      {...props}
    >
      {children}
    </select>
  );
}

export function Card({
  className = "",
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={`rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface-elevated))] p-5 ${className}`}
    >
      {children}
    </div>
  );
}

export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "success" | "warning" | "danger" | "primary";
  children: React.ReactNode;
}) {
  const tones = {
    neutral: "bg-[hsl(var(--muted))] text-[hsl(var(--foreground))]",
    success: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
    warning: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
    danger: "bg-red-500/15 text-red-700 dark:text-red-300",
    primary: "bg-blue-500/15 text-blue-700 dark:text-blue-300",
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${tones[tone]}`}>
      {children}
    </span>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function StatCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint?: string;
}) {
  const formatted = typeof value === "number" ? value.toLocaleString() : value;
  return (
    <Card>
      <div className="text-xs font-medium uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
        {label}
      </div>
      <div className="mt-2 text-2xl font-semibold">{formatted}</div>
      {hint && <div className="mt-1 text-xs text-[hsl(var(--muted-foreground))]">{hint}</div>}
    </Card>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <Card className="flex flex-col items-center justify-center py-12 text-center">
      <h2 className="text-base font-medium">{title}</h2>
      <p className="mt-1 max-w-md text-sm text-[hsl(var(--muted-foreground))]">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </Card>
  );
}

export function PermissionDenied({
  title = "Access Restricted",
  message = "Your current role or API key scopes do not permit this action.",
}: {
  title?: string;
  message?: string;
}) {
  return (
    <Card className="flex flex-col items-center justify-center py-12 text-center">
      <Lock className="h-8 w-8 text-[hsl(var(--muted-foreground))]" aria-hidden="true" />
      <h2 className="mt-3 text-base font-medium">{title}</h2>
      <p className="mt-1 max-w-md text-sm text-[hsl(var(--muted-foreground))]">{message}</p>
    </Card>
  );
}

export function ErrorState({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  if (error instanceof ApiError && error.status === 403) {
    return <PermissionDenied message={error.message} />;
  }
  const msg = error instanceof Error ? error.message : "An unexpected error occurred";
  const reqId = error instanceof ApiError ? error.requestId : undefined;
  return (
    <Card className="border-l-4 border-l-[hsl(var(--destructive))]">
      <div className="flex items-start gap-3">
        <ShieldAlert className="mt-0.5 h-5 w-5 text-[hsl(var(--destructive))]" aria-hidden="true" />
        <div className="flex-1">
          <div className="font-medium">Operation Failed</div>
          <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">{msg}</p>
          {reqId && (
            <div className="mt-1 text-xs font-mono text-[hsl(var(--muted-foreground))]">
              Request ID: {reqId}
            </div>
          )}
          {onRetry && (
            <div className="mt-3">
              <Button size="sm" variant="secondary" onClick={onRetry}>
                Retry
              </Button>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

export function SkeletonTable({ rows = 5 }: { rows?: number }) {
  return (
    <Card className="space-y-3">
      {Array.from({ length: rows }).map((_, idx) => (
        <div key={idx} className="h-8 animate-pulse rounded bg-[hsl(var(--muted))]" />
      ))}
    </Card>
  );
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      type="button"
      size="sm"
      variant="secondary"
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1800);
      }}
    >
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      <span>{copied ? "Copied" : label}</span>
    </Button>
  );
}

export function Modal({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
    >
      <div className="w-full max-w-lg rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface-elevated))] p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button
            type="button"
            aria-label="Close dialog"
            onClick={onClose}
            className="rounded p-1 hover:bg-[hsl(var(--muted))]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel = "Confirm",
  danger = false,
  loading = false,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  description: string;
  confirmLabel?: string;
  danger?: boolean;
  loading?: boolean;
}) {
  return (
    <Modal open={open} onClose={onClose} title={title}>
      <div className="flex items-start gap-3 text-sm text-[hsl(var(--muted-foreground))]">
        {danger && <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-[hsl(var(--destructive))]" />}
        <p>{description}</p>
      </div>
      <div className="mt-6 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose} disabled={loading}>
          Cancel
        </Button>
        <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} disabled={loading}>
          {loading ? "Working..." : confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}
