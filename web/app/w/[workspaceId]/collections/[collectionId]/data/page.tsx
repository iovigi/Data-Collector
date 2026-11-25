import React, { useMemo, useState } from "react";
import { Link, useParams, useRouter } from "@/lib/router";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { Download, Plus, RefreshCw, RotateCcw, Trash2, Upload } from "lucide-react";
import { apiFetch } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type {
  Collection,
  FilterOp,
  JobItem,
  RecordItem,
  SafeFilterNode,
  SavedQuery,
  SearchRecordsResponse,
  WorkspaceCapabilities,
} from "@/lib/api/types";
import { AppShell } from "@/components/layout/AppShell";
import { DeleteCollectionDialog } from "@/components/collections/DeleteCollectionDialog";
import { useToast } from "@/components/providers";
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  CopyButton,
  EmptyState,
  ErrorState,
  Input,
  Modal,
  PageHeader,
  Select,
  SkeletonTable,
} from "@/components/ui/primitives";

interface FilterRow {
  field: string;
  op: FilterOp;
  value: string;
}

const PAGE_SIZE = 25;
const DATE_FIELDS = new Set(["created_at", "updated_at"]);
const FILTER_OPS: FilterOp[] = ["eq", "ne", "gt", "gte", "lt", "lte", "in", "exists", "contains"];

type FieldType = "string" | "number" | "boolean" | "datetime" | "unknown";

/** Resolve a JSON-Schema property type (handles `["string","null"]` unions). */
function schemaFieldType(prop: unknown): FieldType {
  if (!prop || typeof prop !== "object") return "unknown";
  const p = prop as { type?: string | string[]; format?: string };
  const types = Array.isArray(p.type) ? p.type.filter((t) => t !== "null") : [p.type];
  const t = types[0];
  if (t === "number" || t === "integer") return "number";
  if (t === "boolean") return "boolean";
  if (t === "string") return p.format === "date-time" ? "datetime" : "string";
  return "unknown";
}

/** Convert a raw text input into the JSON value the backend compares against. */
function coerceValue(raw: string, type: FieldType): unknown {
  const v = raw.trim();
  switch (type) {
    case "number": {
      const n = Number(v);
      return v !== "" && !Number.isNaN(n) ? n : v;
    }
    case "boolean":
      return v.toLowerCase() === "true" ? true : v.toLowerCase() === "false" ? false : v;
    case "datetime": {
      const d = new Date(v);
      return Number.isNaN(d.getTime()) ? v : d.toISOString();
    }
    case "string":
      return raw;
    default: {
      // No schema type info: best-effort guess.
      if (v === "true") return true;
      if (v === "false") return false;
      const n = Number(v);
      return v !== "" && !Number.isNaN(n) ? n : raw;
    }
  }
}

function buildAst(
  logic: "and" | "or",
  rows: FilterRow[],
  typeOf: (field: string) => FieldType
): SafeFilterNode | null {
  const valid = rows.filter(
    (r) => r.field.trim() !== "" && (r.op === "exists" || r.value.trim() !== "")
  );
  if (valid.length === 0) return null;
  const nodes: SafeFilterNode[] = valid.map((r) => {
    const type = typeOf(r.field);
    let value: unknown;
    if (r.op === "exists") {
      value = r.value !== "false";
    } else if (r.op === "contains") {
      value = r.value;
    } else if (r.op === "in") {
      value = r.value
        .split(",")
        .map((s) => s.trim())
        .filter((s) => s !== "")
        .map((s) => coerceValue(s, type));
    } else {
      value = coerceValue(r.value, type);
    }
    return { field: r.field, op: r.op, value };
  });
  if (nodes.length === 1) return nodes[0]!;
  return logic === "and" ? { and: nodes } : { or: nodes };
}

/** `datetime-local` input value <-> ISO string helpers. */
function toLocalInput(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const off = d.getTimezoneOffset() * 60_000;
  return new Date(d.getTime() - off).toISOString().slice(0, 16);
}

export default function DataExplorerPage() {
  const { workspaceId: wid, collectionId: cid } = useParams<{
    workspaceId: string;
    collectionId: string;
  }>();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  // Filter & cursor pagination state
  const [logic, setLogic] = useState<"and" | "or">("and");
  const [filterRows, setFilterRows] = useState<FilterRow[]>([]);
  const [appliedFilter, setAppliedFilter] = useState<SafeFilterNode | null>(null);
  const [cursorStack, setCursorStack] = useState<Array<string | null>>([null]);
  const currentCursor = cursorStack[cursorStack.length - 1] ?? null;
  const [trashCursorStack, setTrashCursorStack] = useState<Array<string | null>>([null]);
  const trashCursor = trashCursorStack[trashCursorStack.length - 1] ?? null;
  const [tab, setTab] = useState<"active" | "trash">("active");

  // Record Create/Edit/Conflict/Delete modals
  const [openCreate, setOpenCreate] = useState(false);
  const [newJson, setNewJson] = useState('{\n  "name": ""\n}');
  const [editingRecord, setEditingRecord] = useState<RecordItem | null>(null);
  const [editJson, setEditJson] = useState("");
  const [conflictRecord, setConflictRecord] = useState<RecordItem | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<RecordItem | null>(null);

  // Import/Export/SaveQuery modals
  const [openImport, setOpenImport] = useState(false);
  const [openDeleteCollection, setOpenDeleteCollection] = useState(false);
  const router = useRouter();
  const [importFmt, setImportFmt] = useState<"csv" | "json" | "jsonl">("csv");
  const [importDryRun, setImportDryRun] = useState(true);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importJob, setImportJob] = useState<JobItem | null>(null);
  const [openSaveQuery, setOpenSaveQuery] = useState(false);
  const [sqName, setSqName] = useState("");

  const colQuery = useQuery({
    queryKey: ["collection", wid, cid],
    queryFn: () => apiFetch<Collection>(`/collections/${cid}`),
  });

  const capsQuery = useQuery({
    queryKey: ["capabilities", wid],
    queryFn: () => apiFetch<WorkspaceCapabilities>(`/workspaces/${wid}/capabilities`),
  });

  const searchQuery = useQuery({
    queryKey: ["records", wid, cid, JSON.stringify(appliedFilter), currentCursor],
    queryFn: () =>
      apiFetch<SearchRecordsResponse>(`/collections/${cid}/records/search`, {
        method: "POST",
        body: {
          filter: appliedFilter,
          sort: [{ field: "created_at", direction: "desc" }],
          limit: PAGE_SIZE,
          cursor: currentCursor,
        },
      }),
    enabled: tab === "active",
    placeholderData: keepPreviousData,
  });

  const trashQuery = useQuery({
    queryKey: ["records-trash", wid, cid, trashCursor],
    queryFn: () => {
      const qs = new URLSearchParams({ limit: String(PAGE_SIZE) });
      if (trashCursor) qs.set("cursor", trashCursor);
      return apiFetch<SearchRecordsResponse>(`/collections/${cid}/records/trash?${qs}`);
    },
    enabled: tab === "trash",
    placeholderData: keepPreviousData,
  });

  const createMutation = useMutation({
    mutationFn: () => {
      const parsed = JSON.parse(newJson) as Record<string, unknown>;
      return apiFetch<RecordItem>(`/collections/${cid}/records`, {
        method: "POST",
        headers: { "Idempotency-Key": `ui-${Date.now()}-${Math.random().toString(36).slice(2, 8)}` },
        body: { data: parsed },
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["records", wid, cid] });
      setOpenCreate(false);
      toast({ title: "Record created", variant: "success" });
    },
    onError: (err: Error) =>
      toast({ title: "Create failed", description: err.message, variant: "error" }),
  });

  const updateMutation = useMutation({
    mutationFn: () => {
      if (!editingRecord) throw new Error("No record selected");
      const patch = JSON.parse(editJson) as Record<string, unknown>;
      return apiFetch<RecordItem>(`/collections/${cid}/records/${editingRecord.id}`, {
        method: "PATCH",
        body: { patch, expected_version: editingRecord.version },
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["records", wid, cid] });
      setEditingRecord(null);
      toast({ title: "Record updated", variant: "success" });
    },
    onError: async (err: unknown) => {
      if (err instanceof ApiError && err.status === 409 && editingRecord) {
        const fresh = await apiFetch<RecordItem>(`/collections/${cid}/records/${editingRecord.id}`);
        setConflictRecord(fresh);
        toast({
          title: "Version conflict (409)",
          description: "Record was modified by another user. Review server version below.",
          variant: "error",
        });
      } else {
        toast({
          title: "Update failed",
          description: err instanceof Error ? err.message : "Error",
          variant: "error",
        });
      }
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (rec: RecordItem) =>
      apiFetch(`/collections/${cid}/records/${rec.id}`, {
        method: "DELETE",
        body: { expected_version: rec.version },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["records", wid, cid] });
      queryClient.invalidateQueries({ queryKey: ["records-trash", wid, cid] });
      setDeleteTarget(null);
      toast({ title: "Record moved to trash", variant: "success" });
    },
    onError: (err: Error) =>
      toast({ title: "Delete failed", description: err.message, variant: "error" }),
  });

  const restoreMutation = useMutation({
    mutationFn: (rid: string) =>
      apiFetch<RecordItem>(`/collections/${cid}/records/${rid}/restore`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["records", wid, cid] });
      queryClient.invalidateQueries({ queryKey: ["records-trash", wid, cid] });
      toast({ title: "Record restored", variant: "success" });
    },
  });

  const exportMutation = useMutation({
    mutationFn: (fmt: "csv" | "jsonl") =>
      apiFetch<JobItem>(`/collections/${cid}/exports`, {
        method: "POST",
        body: { format: fmt, filter: appliedFilter },
      }),
    onSuccess: (job) => {
      toast({ title: `Export ${job.state}`, description: `Job ID: ${job.id}`, variant: "success" });
      if (job.state === "completed") {
        window.open(`/api/backend/jobs/${job.id}/result`, "_blank", "noopener");
      }
    },
    onError: (err: Error) =>
      toast({ title: "Export failed", description: err.message, variant: "error" }),
  });

  async function handleImportSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!importFile) return;
    try {
      const buf = await importFile.arrayBuffer();
      const job = await apiFetch<JobItem>(
        `/collections/${cid}/imports?format=${importFmt}&dry_run=${importDryRun}`,
        {
          method: "POST",
          rawBody: buf,
          contentType: "application/octet-stream",
          headers: { "Idempotency-Key": `imp-${Date.now()}` },
        }
      );
      setImportJob(job);
      queryClient.invalidateQueries({ queryKey: ["records", wid, cid] });
      toast({ title: `Import ${job.state}`, variant: "success" });
    } catch (err) {
      toast({
        title: "Import failed",
        description: err instanceof Error ? err.message : "Error",
        variant: "error",
      });
    }
  }

  const saveQueryMutation = useMutation({
    mutationFn: () =>
      apiFetch<SavedQuery>(`/collections/${cid}/saved-queries`, {
        method: "POST",
        body: { name: sqName.trim(), filter: appliedFilter },
      }),
    onSuccess: () => {
      setOpenSaveQuery(false);
      setSqName("");
      toast({ title: "Saved query created", variant: "success" });
    },
    onError: (err: Error) =>
      toast({ title: "Save query failed", description: err.message, variant: "error" }),
  });

  const schemaPropDefs = useMemo(
    () =>
      (colQuery.data?.schema_json as { properties?: Record<string, unknown> } | undefined)
        ?.properties ?? {},
    [colQuery.data]
  );
  const schemaProps = useMemo(() => Object.keys(schemaPropDefs), [schemaPropDefs]);

  // Same allowlist the backend enforces: schema properties ∪ searchable_fields,
  // plus the built-in timestamp metadata fields.
  const searchableFields = useMemo(() => {
    const fields = new Set<string>([
      ...(colQuery.data?.searchable_fields ?? []),
      ...schemaProps,
    ]);
    return [...fields, ...[...DATE_FIELDS].filter((f) => !fields.has(f))];
  }, [colQuery.data, schemaProps]);

  const fieldType = (field: string): FieldType =>
    DATE_FIELDS.has(field) ? "datetime" : schemaFieldType(schemaPropDefs[field]);

  const applyFilters = () => {
    setAppliedFilter(buildAst(logic, filterRows, fieldType));
    setCursorStack([null]);
  };

  const updateRow = (idx: number, patch: Partial<FilterRow>) =>
    setFilterRows((prev) => prev.map((item, i) => (i === idx ? { ...item, ...patch } : item)));

  const caps = capsQuery.data?.features;

  const columns = useMemo<ColumnDef<RecordItem>[]>(() => {
    const dataCols: ColumnDef<RecordItem>[] = schemaProps.slice(0, 6).map((field) => ({
      id: `data.${field}`,
      header: field,
      cell: ({ row }) => {
        const val = row.original.data[field];
        if (val === undefined || val === null) {
          return <span className="text-[hsl(var(--muted-foreground))]">—</span>;
        }
        return (
          <span className="block max-w-[220px] truncate font-mono text-xs">
            {typeof val === "object" ? JSON.stringify(val) : String(val)}
          </span>
        );
      },
    }));

    return [
      ...dataCols,
      {
        id: "version",
        header: "Ver",
        cell: ({ row }) => <Badge>v{row.original.version}</Badge>,
      },
      {
        id: "actions",
        header: "Actions",
        cell: ({ row }) => {
          const rec = row.original;
          return (
            <div className="flex items-center gap-1.5">
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  setEditingRecord(rec);
                  setEditJson(JSON.stringify(rec.data, null, 2));
                  setConflictRecord(null);
                }}
              >
                {caps?.can_write_records ? "Edit" : "View"}
              </Button>
              {tab === "active" && caps?.can_delete_records && (
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Delete record ${rec.id}`}
                  onClick={() => setDeleteTarget(rec)}
                >
                  <Trash2 className="h-3.5 w-3.5 text-[hsl(var(--destructive))]" />
                </Button>
              )}
              {tab === "trash" && caps?.can_write_records && (
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => restoreMutation.mutate(rec.id)}
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  Restore
                </Button>
              )}
            </div>
          );
        },
      },
    ];
  }, [schemaProps, caps, tab, restoreMutation]);

  const currentQuery = tab === "active" ? searchQuery : trashQuery;
  const activeRows = currentQuery.data?.items ?? [];
  const pageStack = tab === "active" ? cursorStack : trashCursorStack;
  const setPageStack = tab === "active" ? setCursorStack : setTrashCursorStack;

  const table = useReactTable({
    data: activeRows,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <AppShell workspaceId={wid}>
      <PageHeader
        title={`Data Explorer · ${colQuery.data?.slug ?? "Collection"}`}
        subtitle="Safe Query DSL filtering, cursor pagination, schema-validated editing & jobs"
        actions={
          <>
            <Link href={`/w/${wid}/collections/${cid}/schema`}>
              <Button size="sm" variant="secondary">
                Schema (v{colQuery.data?.schema_version ?? 1})
              </Button>
            </Link>
            {caps?.can_export && (
              <Button size="sm" variant="secondary" onClick={() => exportMutation.mutate("csv")}>
                <Download className="h-3.5 w-3.5" />
                Export CSV
              </Button>
            )}
            {caps?.can_create_jobs && (
              <Button size="sm" variant="secondary" onClick={() => setOpenImport(true)}>
                <Upload className="h-3.5 w-3.5" />
                Import
              </Button>
            )}
            {caps?.can_delete_collections && (
              <Button size="sm" variant="danger" onClick={() => setOpenDeleteCollection(true)}>
                <Trash2 className="h-3.5 w-3.5" />
                Delete collection
              </Button>
            )}
            {caps?.can_write_records && (
              <Button size="sm" onClick={() => setOpenCreate(true)}>
                <Plus className="h-3.5 w-3.5" />
                New Record
              </Button>
            )}
          </>
        }
      />

      {/* Tabs: Active vs Trash */}
      <div className="mb-4 flex items-center gap-2 border-b border-[hsl(var(--border))] pb-2">
        <Button
          size="sm"
          variant={tab === "active" ? "primary" : "ghost"}
          onClick={() => setTab("active")}
        >
          Active Records
        </Button>
        <Button
          size="sm"
          variant={tab === "trash" ? "primary" : "ghost"}
          onClick={() => setTab("trash")}
        >
          Trash (Soft Deleted)
        </Button>
      </div>

      {/* Filter Builder */}
      {tab === "active" && (
        <Card className="mb-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold uppercase text-[hsl(var(--muted-foreground))]">
                Filter Logic
              </span>
              <Select
                aria-label="Logical operator"
                value={logic}
                onChange={(e) => setLogic(e.target.value as "and" | "or")}
              >
                <option value="and">AND (all match)</option>
                <option value="or">OR (any match)</option>
              </Select>
              <Button
                size="sm"
                variant="secondary"
                onClick={() =>
                  setFilterRows((r) => [
                    ...r,
                    { field: searchableFields[0] ?? "", op: "eq", value: "" },
                  ])
                }
              >
                + Add condition
              </Button>
            </div>
            <div className="flex items-center gap-2">
              {caps?.can_manage_collections && (
                <Button size="sm" variant="secondary" onClick={() => setOpenSaveQuery(true)}>
                  Save Query
                </Button>
              )}
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setFilterRows([]);
                  setAppliedFilter(null);
                  setCursorStack([null]);
                }}
              >
                Reset
              </Button>
              <Button size="sm" onClick={applyFilters}>
                Apply Filters
              </Button>
            </div>
          </div>

          <form
            className="space-y-2"
            onSubmit={(e) => {
              e.preventDefault();
              applyFilters();
            }}
          >
            {filterRows.map((row, idx) => {
              const type = fieldType(row.field);
              return (
                <div key={idx} className="flex flex-wrap items-center gap-2">
                  <Select
                    aria-label={`Filter field ${idx + 1}`}
                    value={row.field}
                    onChange={(e) => updateRow(idx, { field: e.target.value, value: "" })}
                  >
                    {!searchableFields.includes(row.field) && (
                      <option value="" disabled>
                        Select field…
                      </option>
                    )}
                    {searchableFields.map((f) => (
                      <option key={f} value={f}>
                        {f}
                      </option>
                    ))}
                  </Select>
                  <Select
                    aria-label={`Filter operator ${idx + 1}`}
                    value={row.op}
                    onChange={(e) => {
                      const op = e.target.value as FilterOp;
                      updateRow(idx, op === "exists" ? { op, value: "true" } : { op });
                    }}
                  >
                    {FILTER_OPS.map((op) => (
                      <option key={op} value={op}>
                        {op}
                      </option>
                    ))}
                  </Select>
                  {row.op === "exists" ? (
                    <Select
                      aria-label={`Filter value ${idx + 1}`}
                      value={row.value === "false" ? "false" : "true"}
                      onChange={(e) => updateRow(idx, { value: e.target.value })}
                    >
                      <option value="true">exists</option>
                      <option value="false">missing</option>
                    </Select>
                  ) : type === "boolean" && row.op !== "in" ? (
                    <Select
                      aria-label={`Filter value ${idx + 1}`}
                      value={row.value}
                      onChange={(e) => updateRow(idx, { value: e.target.value })}
                    >
                      <option value="">Select…</option>
                      <option value="true">true</option>
                      <option value="false">false</option>
                    </Select>
                  ) : type === "datetime" && row.op !== "in" && row.op !== "contains" ? (
                    <Input
                      aria-label={`Filter value ${idx + 1}`}
                      type="datetime-local"
                      className="max-w-xs"
                      value={row.value ? toLocalInput(row.value) : ""}
                      onChange={(e) =>
                        updateRow(idx, {
                          value: e.target.value ? new Date(e.target.value).toISOString() : "",
                        })
                      }
                    />
                  ) : (
                    <Input
                      aria-label={`Filter value ${idx + 1}`}
                      className="max-w-xs"
                      type={type === "number" && row.op !== "in" ? "number" : "text"}
                      value={row.value}
                      onChange={(e) => updateRow(idx, { value: e.target.value })}
                      placeholder={row.op === "in" ? "value1, value2, …" : "Value..."}
                    />
                  )}
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => setFilterRows((prev) => prev.filter((_, i) => i !== idx))}
                  >
                    Remove
                  </Button>
                </div>
              );
            })}
            {/* Enables Enter-to-apply from any input */}
            <button type="submit" hidden aria-hidden tabIndex={-1} />
          </form>
        </Card>
      )}

      {/* Records Table */}
      {currentQuery.isLoading && <SkeletonTable rows={6} />}
      {currentQuery.isError && (
        <ErrorState error={currentQuery.error} onRetry={() => currentQuery.refetch()} />
      )}

      {currentQuery.isSuccess && activeRows.length === 0 && (
        <EmptyState
          title={tab === "active" ? "No records match" : "Trash is empty"}
          description={
            tab === "active"
              ? "Add a record or adjust your filter criteria."
              : "Soft-deleted records appear here within the retention window."
          }
        />
      )}

      {activeRows.length > 0 && (
        <Card className="overflow-x-auto p-0">
          <table className="w-full border-collapse text-left text-sm">
            <thead className="border-b border-[hsl(var(--border))] bg-[hsl(var(--surface))] text-xs uppercase text-[hsl(var(--muted-foreground))]">
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id}>
                  {hg.headers.map((header) => (
                    <th key={header.id} className="px-4 py-3 font-medium">
                      {flexRender(header.column.columnDef.header, header.getContext())}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody className="divide-y divide-[hsl(var(--border))]">
              {table.getRowModel().rows.map((row) => (
                <tr key={row.id} className="hover:bg-[hsl(var(--surface))]">
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-4 py-2.5">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* Cursor Pagination Controls */}
      {currentQuery.data && (pageStack.length > 1 || currentQuery.data.has_more) && (
        <div className="mt-4 flex items-center justify-between">
          <div className="text-xs text-[hsl(var(--muted-foreground))]">
            Page {pageStack.length} · Records {(pageStack.length - 1) * PAGE_SIZE + (activeRows.length ? 1 : 0)}
            –{(pageStack.length - 1) * PAGE_SIZE + activeRows.length}
            {currentQuery.isFetching && " · Loading…"}
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="secondary"
              disabled={pageStack.length <= 1 || currentQuery.isFetching}
              onClick={() => setPageStack((s) => s.slice(0, -1))}
            >
              Previous
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={
                currentQuery.isFetching ||
                currentQuery.isPlaceholderData ||
                !currentQuery.data.has_more ||
                !currentQuery.data.next_cursor
              }
              onClick={() => {
                const next = currentQuery.data?.next_cursor;
                if (next) setPageStack((s) => [...s, next]);
              }}
            >
              Next
            </Button>
          </div>
        </div>
      )}

      {/* Create Record Modal */}
      <Modal open={openCreate} onClose={() => setOpenCreate(false)} title="Create Record">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            createMutation.mutate();
          }}
          className="space-y-4"
        >
          <textarea
            aria-label="New record JSON"
            rows={10}
            value={newJson}
            onChange={(e) => setNewJson(e.target.value)}
            className="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3 font-mono text-xs"
          />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setOpenCreate(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={createMutation.isPending}>
              {createMutation.isPending ? "Saving..." : "Create Record"}
            </Button>
          </div>
        </form>
      </Modal>

      {/* Edit / View Record Modal (with 409 Conflict Resolution) */}
      <Modal
        open={Boolean(editingRecord)}
        onClose={() => {
          setEditingRecord(null);
          setConflictRecord(null);
        }}
        title={
          editingRecord
            ? `Record ${editingRecord.id.slice(-8)} (v${editingRecord.version})`
            : "Record"
        }
      >
        {editingRecord && (
          <div className="space-y-3">
            <div className="flex items-center justify-between text-xs text-[hsl(var(--muted-foreground))]">
              <span className="font-mono">{editingRecord.id}</span>
              <CopyButton text={editingRecord.id} label="Copy ID" />
            </div>

            {conflictRecord && (
              <div className="rounded-md border border-[hsl(var(--destructive))] bg-red-500/10 p-3 text-xs">
                <div className="font-semibold text-[hsl(var(--destructive))]">
                  409 Conflict — Server is now at v{conflictRecord.version}
                </div>
                <pre className="mt-2 max-h-32 overflow-auto rounded bg-[hsl(var(--background))] p-2 font-mono">
                  {JSON.stringify(conflictRecord.data, null, 2)}
                </pre>
                <Button
                  size="sm"
                  variant="secondary"
                  className="mt-2"
                  onClick={() => {
                    setEditingRecord(conflictRecord);
                    setEditJson(JSON.stringify(conflictRecord.data, null, 2));
                    setConflictRecord(null);
                  }}
                >
                  <RefreshCw className="h-3 w-3" />
                  Reload Server Version
                </Button>
              </div>
            )}

            <textarea
              aria-label="Record JSON data"
              rows={10}
              readOnly={!caps?.can_write_records}
              value={editJson}
              onChange={(e) => setEditJson(e.target.value)}
              className="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3 font-mono text-xs"
            />
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setEditingRecord(null)}>
                Close
              </Button>
              {caps?.can_write_records && (
                <Button onClick={() => updateMutation.mutate()} disabled={updateMutation.isPending}>
                  {updateMutation.isPending ? "Saving..." : "Save Changes"}
                </Button>
              )}
            </div>
          </div>
        )}
      </Modal>

      {/* Soft Delete Confirmation */}
      <ConfirmDialog
        open={Boolean(deleteTarget)}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget)}
        title="Soft Delete Record"
        description={`Move record ${deleteTarget?.id ?? ""} (v${deleteTarget?.version ?? 1}) to Trash? You can restore it within the retention window.`}
        confirmLabel="Move to Trash"
        danger
        loading={deleteMutation.isPending}
      />

      {/* Raw-byte Import Modal */}
      <Modal open={openImport} onClose={() => setOpenImport(false)} title="Import Records">
        <form onSubmit={handleImportSubmit} className="space-y-4">
          <div>
            <label htmlFor="imp-fmt" className="mb-1 block text-sm font-medium">
              Format
            </label>
            <Select
              id="imp-fmt"
              value={importFmt}
              onChange={(e) => setImportFmt(e.target.value as "csv" | "json" | "jsonl")}
            >
              <option value="csv">CSV</option>
              <option value="json">JSON Array</option>
              <option value="jsonl">JSONL / NDJSON</option>
            </Select>
          </div>
          <div>
            <label htmlFor="imp-file" className="mb-1 block text-sm font-medium">
              File
            </label>
            <input
              id="imp-file"
              type="file"
              required
              onChange={(e) => setImportFile(e.target.files?.[0] ?? null)}
              className="block w-full text-sm"
            />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={importDryRun}
              onChange={(e) => setImportDryRun(e.target.checked)}
            />
            <span>Dry-run validation only (do not insert records)</span>
          </label>
          {importJob && (
            <div className="rounded border border-[hsl(var(--border))] p-3 text-xs">
              <div>
                State: <strong>{importJob.state}</strong> · Succeeded:{" "}
                {importJob.progress.succeeded} · Failed: {importJob.progress.failed}
              </div>
              {importJob.errors && importJob.errors.length > 0 && (
                <pre className="mt-2 max-h-28 overflow-auto font-mono text-red-600">
                  {JSON.stringify(importJob.errors.slice(0, 10), null, 2)}
                </pre>
              )}
            </div>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setOpenImport(false)}>
              Close
            </Button>
            <Button type="submit">Run Import</Button>
          </div>
        </form>
      </Modal>

      {/* Save Query Modal */}
      <Modal open={openSaveQuery} onClose={() => setOpenSaveQuery(false)} title="Save Query">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            saveQueryMutation.mutate();
          }}
          className="space-y-4"
        >
          <div>
            <label htmlFor="sq-name" className="mb-1 block text-sm font-medium">
              Query Name
            </label>
            <Input
              id="sq-name"
              required
              value={sqName}
              onChange={(e) => setSqName(e.target.value)}
              placeholder="Qualified Leads"
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setOpenSaveQuery(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={saveQueryMutation.isPending}>
              Save
            </Button>
          </div>
        </form>
      </Modal>
      <DeleteCollectionDialog
        open={openDeleteCollection}
        onClose={() => setOpenDeleteCollection(false)}
        collectionId={cid}
        onDeleted={(res) => {
          setOpenDeleteCollection(false);
          queryClient.removeQueries({ queryKey: ["collection", wid, cid] });
          queryClient.invalidateQueries({ queryKey: ["collections"] });
          toast({
            title: `Deleted ${res.slug}`,
            description: `${res.records_deleted.toLocaleString()} records removed`,
            variant: "success",
          });
          router.push(`/w/${wid}/collections`);
        }}
      />
    </AppShell>
  );
}
