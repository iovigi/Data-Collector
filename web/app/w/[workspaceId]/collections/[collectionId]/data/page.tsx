import React, { useMemo, useState } from "react";
import { Link, useParams, useRouter } from "@/lib/router";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { ChevronDown, Download, Eye, Pencil, Plus, RefreshCw, RotateCcw, Trash2, Upload } from "lucide-react";
import { apiFetch } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type {
  Collection,
  CollectionCountResponse,
  FilterOp,
  FulltextSearchHit,
  FulltextSearchResponse,
  JobItem,
  RecordItem,
  SafeFilterNode,
  SavedQuery,
  SearchRecordsResponse,
  SearchStatusResponse,
  WorkspaceCapabilities,
} from "@/lib/api/types";
import { AppShell } from "@/components/layout/AppShell";
import { DeleteCollectionDialog } from "@/components/collections/DeleteCollectionDialog";
import { CountBadge } from "@/components/data/CountBadge";
import { FieldVisibilityPicker, discoverRecordPaths } from "@/components/data/FieldVisibilityPicker";
import { FullTextSearchBar } from "@/components/data/FullTextSearchBar";
import { NestedValuePreview, getNestedValue } from "@/components/data/NestedValuePreview";
import { RecordDetailDrawer } from "@/components/data/RecordDetailDrawer";
import { useToast } from "@/components/providers";
import {
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
const FILTER_OPS: FilterOp[] = [
  "eq",
  "ne",
  "gt",
  "gte",
  "lt",
  "lte",
  "in",
  "between",
  "array_contains",
  "exists",
];

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
      return v !== "" && Number.isFinite(n) ? n : v;
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
      return v !== "" && Number.isFinite(n) ? n : raw;
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
    } else if (r.op === "between") {
      const parts = r.value
        .split(",")
        .map((s) => s.trim())
        .filter((s) => s !== "")
        .slice(0, 2)
        .map((s) => coerceValue(s, type));
      value = parts;
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

function SearchMatch({ hit }: { hit?: FulltextSearchHit }) {
  return (
    <div className="min-w-36 space-y-1 text-xs">
      {hit?.highlights.slice(0, 2).map(({ path, text }) => (
        <div key={path}>
          <div className="break-all font-medium text-[hsl(var(--muted-foreground))]">{path}</div>
          <div className="line-clamp-3 break-words">{decodeSnippet(text)}</div>
        </div>
      ))}
    </div>
  );
}

function decodeSnippet(text: string) {
  const escapes: Record<string, string> = {
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&#x27;": "'",
  };
  return text.replace(/&(?:amp|lt|gt|quot|#x27);/g, (entity) => escapes[entity]!);
}

export default function DataExplorerPage() {
  const { workspaceId: wid, collectionId: cid } = useParams<{
    workspaceId: string;
    collectionId: string;
  }>();
  return <DataExplorer key={`${wid}:${cid}`} wid={wid} cid={cid} />;
}

function DataExplorer({ wid, cid }: { wid: string; cid: string }) {
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
  const [searchMode, setSearchMode] = useState<"structured" | "fulltext">("structured");
  const [fulltextQueryText, setFulltextQueryText] = useState<string | null>(null);
  const [fulltextDraft, setFulltextDraft] = useState("");
  const [fulltextCursorStack, setFulltextCursorStack] = useState<Array<string | null>>([null]);
  const fulltextCursor = fulltextCursorStack.at(-1) ?? null;
  const isFulltext = tab === "active" && searchMode === "fulltext";
  const [filterError, setFilterError] = useState<string | null>(null);
  const [inspectedRecord, setInspectedRecord] = useState<RecordItem | null>(null);
  const [customColumns, setCustomColumns] = useState<string[] | null>(() => {
    if (typeof window === "undefined") return null;
    try {
      const raw = window.localStorage.getItem(`dc:cols:${wid}:${cid}`);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string") : null;
    } catch {
      return null;
    }
  });

  // Record Create/Edit/Conflict/Delete modals
  const [openCreate, setOpenCreate] = useState(false);
  const [newJson, setNewJson] = useState('{\n  "name": ""\n}');
  const [editingRecord, setEditingRecord] = useState<RecordItem | null>(null);
  const [editJson, setEditJson] = useState("");
  const [editError, setEditError] = useState<string | null>(null);
  const [conflictRecord, setConflictRecord] = useState<RecordItem | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<RecordItem | null>(null);

  // Import/Export/SaveQuery modals
  const [showActions, setShowActions] = useState(false);
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

  const countQuery = useQuery({
    queryKey: ["collection-count", wid, cid],
    queryFn: () => apiFetch<CollectionCountResponse>(`/collections/${cid}/record-count`),
    staleTime: 60_000,
  });

  const refreshCountMutation = useMutation({
    mutationFn: () =>
      apiFetch<CollectionCountResponse>(`/collections/${cid}/record-count/refresh`, {
        method: "POST",
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["collection-count", wid, cid], data);
      queryClient.invalidateQueries({ queryKey: ["collection-counts-batch", wid] });
      const available = data.active.value !== null;
      toast({
        title: available ? "Record count refreshed" : "Record count is unavailable",
        variant: available ? "success" : "default",
      });
    },
    onError: (err: Error) =>
      toast({ title: "Count refresh failed", description: err.message, variant: "error" }),
  });

  const searchStatusQuery = useQuery({
    queryKey: ["search-status", wid, cid],
    queryFn: () => apiFetch<SearchStatusResponse>(`/collections/${cid}/search/status`),
    enabled: isFulltext,
    staleTime: 30_000,
    retry: false,
    refetchInterval: (query) => query.state.data?.state === "indexing" ? 10_000 : false,
  });

  const fulltextQuery = useQuery({
    queryKey: ["records-fulltext", wid, cid, fulltextQueryText, fulltextCursor],
    queryFn: ({ signal }) =>
      apiFetch<FulltextSearchResponse>(`/collections/${cid}/records/fulltext`, {
        method: "POST",
        body: {
          query: fulltextQueryText,
          limit: PAGE_SIZE,
          cursor: fulltextCursor,
        },
        signal,
      }),
    enabled: isFulltext && Boolean(fulltextQueryText),
    retry: false,
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
    enabled: tab === "active" && searchMode === "structured",
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
      queryClient.invalidateQueries({ queryKey: ["records-fulltext", wid, cid] });
      setOpenCreate(false);
      toast({ title: "Record created", variant: "success" });
    },
    onError: (err: Error) =>
      toast({ title: "Create failed", description: err.message, variant: "error" }),
  });

  const updateMutation = useMutation({
    mutationFn: () => {
      if (!editingRecord) throw new Error("No record selected");
      const next: unknown = JSON.parse(editJson);
      if (!next || typeof next !== "object" || Array.isArray(next)) {
        throw new Error("Enter a JSON object.");
      }
      const previous = editingRecord.data;
      const patch = Object.fromEntries(Object.entries(next).filter(([key, value]) => {
        if (Object.hasOwn(previous, key) && JSON.stringify(previous[key]) === JSON.stringify(value)) {
          return false;
        }
        if (value === null) {
          throw new Error(`The API uses null to remove a top-level field. Remove the key “${key}” to delete it.`);
        }
        return true;
      }));
      for (const key of Object.keys(previous)) {
        if (!Object.hasOwn(next, key)) {
          Object.defineProperty(patch, key, { value: null, enumerable: true });
        }
      }
      if (Object.keys(patch).length === 0) throw new Error("Make a change before saving.");
      return apiFetch<RecordItem>(`/collections/${cid}/records/${editingRecord.id}`, {
        method: "PATCH",
        body: { patch, expected_version: editingRecord.version },
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["records", wid, cid] });
      queryClient.invalidateQueries({ queryKey: ["records-fulltext", wid, cid] });
      setEditingRecord(null);
      toast({ title: "Record updated", variant: "success" });
    },
    onError: async (err: unknown) => {
      if (err instanceof ApiError && err.status === 409 && editingRecord) {
        try {
          const fresh = await apiFetch<RecordItem>(`/collections/${cid}/records/${editingRecord.id}`);
          setConflictRecord(fresh);
          setEditError("Another change was saved first. Review the latest version below.");
        } catch {
          setEditError("The record changed and the latest version could not be loaded.");
        }
      } else {
        setEditError(err instanceof Error ? err.message : "Could not save the record.");
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
      queryClient.invalidateQueries({ queryKey: ["records-fulltext", wid, cid] });
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
      queryClient.invalidateQueries({ queryKey: ["records-fulltext", wid, cid] });
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
      queryClient.invalidateQueries({ queryKey: ["records-fulltext", wid, cid] });
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
  const schemaPaths = useMemo(
    () => discoverRecordPaths(schemaPropDefs, []).map(({ path }) => path),
    [schemaPropDefs]
  );

  // Same allowlist the backend enforces: schema properties ∪ searchable_fields,
  // plus the built-in timestamp metadata fields.
  const searchableFields = useMemo(() => {
    const fields = new Set<string>([
      ...(colQuery.data?.searchable_fields ?? []),
      ...schemaPaths.filter((path) => /^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*$/.test(path)),
    ]);
    return [...fields, ...[...DATE_FIELDS].filter((f) => !fields.has(f))];
  }, [colQuery.data, schemaPaths]);

  const fieldType = (field: string): FieldType => {
    if (DATE_FIELDS.has(field)) return "datetime";
    let properties: Record<string, unknown> | undefined = schemaPropDefs;
    let definition: unknown;
    for (const part of field.split(".")) {
      definition = properties?.[part];
      properties = (definition as { properties?: Record<string, unknown> } | undefined)?.properties;
    }
    return schemaFieldType(definition);
  };

  const applyFilters = () => {
    const invalid = filterRows.findIndex((row) => {
      if (!row.field || !row.value.trim()) return true;
      if (row.op === "between") {
        const [from, to] = row.value.split(",");
        return !from?.trim() || !to?.trim();
      }
      return false;
    });
    if (invalid !== -1) {
      setFilterError(`Complete condition ${invalid + 1} before applying filters.`);
      return;
    }
    setFilterError(null);
    setAppliedFilter(buildAst(logic, filterRows, fieldType));
    setCursorStack([null]);
  };

  const updateRow = (idx: number, patch: Partial<FilterRow>) =>
    setFilterRows((prev) => prev.map((item, i) => (i === idx ? { ...item, ...patch } : item)));

  const caps = capsQuery.data?.features;

  const currentQuery = tab === "trash" ? trashQuery : isFulltext ? fulltextQuery : searchQuery;
  const activeRows: RecordItem[] = useMemo(() => {
    if (isFulltext) return (fulltextQuery.data?.items ?? []).map((hit) => hit.record);
    return (tab === "trash" ? trashQuery.data?.items : searchQuery.data?.items) ?? [];
  }, [tab, isFulltext, fulltextQuery.data, trashQuery.data, searchQuery.data]);

  const fulltextHits = useMemo(
    () => new Map((fulltextQuery.data?.items ?? []).map((hit) => [hit.record.id, hit])),
    [fulltextQuery.data]
  );
  const canEdit = tab === "active" && caps?.can_write_records === true;
  const canExport = tab === "active" && !isFulltext && caps?.can_export;
  const canImport = tab === "active" && caps?.can_create_jobs;
  const canDeleteCollection = tab === "active" && caps?.can_delete_collections;

  const discoveredPaths = useMemo(
    () => discoverRecordPaths(schemaPropDefs, activeRows),
    [schemaPropDefs, activeRows]
  );

  const visibleColumns = useMemo(() => {
    if (customColumns) return customColumns;
    return discoveredPaths.slice(0, 6).map((p) => p.path);
  }, [customColumns, discoveredPaths]);

  const handleColumnsChange = (next: string[]) => {
    setCustomColumns(next);
    if (typeof window !== "undefined") {
      try {
        window.localStorage.setItem(`dc:cols:${wid}:${cid}`, JSON.stringify(next));
      } catch {
        // ignore storage quota errors
      }
    }
  };

  function openEditor(record: RecordItem) {
    setInspectedRecord(null);
    setEditingRecord(record);
    setEditJson(JSON.stringify(record.data, null, 2));
    setEditError(null);
    setConflictRecord(null);
  }

  const columns = useMemo<ColumnDef<RecordItem>[]>(() => {
    const dataCols: ColumnDef<RecordItem>[] = visibleColumns.map((field) => ({
      id: `data.${field}`,
      header: field,
      cell: ({ row }) => (
        <NestedValuePreview value={getNestedValue(row.original.data, field)} />
      ),
    }));

    return [
      {
        id: "record",
        header: "Record",
        cell: ({ row }) => {
          const rec = row.original;
          return (
            <div className="space-y-1">
              <div className="flex items-center gap-1 whitespace-nowrap">
                <Button size="sm" variant="secondary" onClick={() => setInspectedRecord(rec)}>
                  <Eye className="h-3.5 w-3.5" aria-hidden="true" />
                  View
                </Button>
                {canEdit && (
                  <Button size="sm" variant="secondary" onClick={() => openEditor(rec)}>
                    <Pencil className="h-3 w-3" aria-hidden="true" />
                    Edit
                  </Button>
                )}
                {tab === "trash" && caps?.can_write_records && (
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={restoreMutation.isPending}
                    onClick={() => restoreMutation.mutate(rec.id)}
                  >
                    <RotateCcw className="h-3.5 w-3.5" />
                    Restore
                  </Button>
                )}
              </div>
              <div className="font-mono text-[11px] text-[hsl(var(--muted-foreground))]" title={rec.id}>
                …{rec.id.slice(-8)} · v{rec.version}
              </div>
            </div>
          );
        },
      },
      ...(isFulltext ? [{
        id: "match",
        header: "Match",
        cell: ({ row }: { row: { original: RecordItem } }) => (
          <SearchMatch hit={fulltextHits.get(row.original.id)} />
        ),
      }] : []),
      ...dataCols,
      ...(tab === "active" && caps?.can_delete_records ? [{
        id: "actions",
        header: "Manage",
        cell: ({ row }: { row: { original: RecordItem } }) => (
          <Button
            size="sm"
            variant="ghost"
            aria-label={`Delete record ${row.original.id}`}
            onClick={() => setDeleteTarget(row.original)}
          >
            <Trash2 className="h-3.5 w-3.5 text-[hsl(var(--destructive))]" />
          </Button>
        ),
      }] : []),
    ];
  }, [visibleColumns, canEdit, caps, tab, restoreMutation, isFulltext, fulltextHits]);

  const pageStack = tab === "trash" ? trashCursorStack : isFulltext ? fulltextCursorStack : cursorStack;
  const setPageStack = tab === "trash"
    ? setTrashCursorStack
    : isFulltext ? setFulltextCursorStack : setCursorStack;

  const table = useReactTable({
    data: activeRows,
    columns,
    getRowId: (record) => record.id,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <AppShell workspaceId={wid}>
      <PageHeader
        title={`Data Explorer · ${colQuery.data?.slug ?? "Collection"}`}
        actions={
          <>
            <CountBadge
              bucket={countQuery.data?.active}
              label="Active records"
              loading={countQuery.isPending}
              unavailable={countQuery.isError}
              onRefresh={() => refreshCountMutation.mutate()}
              refreshing={refreshCountMutation.isPending}
            />
            {caps?.can_write_records && (
              <Button size="sm" onClick={() => setOpenCreate(true)}>
                <Plus className="h-3.5 w-3.5" />
                New Record
              </Button>
            )}
          </>
        }
      />

      {capsQuery.isError && (
        <div className="mb-4 flex flex-wrap items-center gap-2 text-sm" role="status">
          Record permissions could not be loaded.
          <Button size="sm" variant="secondary" onClick={() => capsQuery.refetch()}>
            Retry permissions
          </Button>
        </div>
      )}

      {/* Tabs: Active vs Trash */}
      <div className="mb-4 flex items-center gap-2 border-b border-[hsl(var(--border))] pb-2">
        <Button
          size="sm"
          variant={tab === "active" ? "primary" : "ghost"}
          aria-pressed={tab === "active"}
          onClick={() => setTab("active")}
        >
          Active Records
        </Button>
        <Button
          size="sm"
          variant={tab === "trash" ? "primary" : "ghost"}
          aria-pressed={tab === "trash"}
          onClick={() => setTab("trash")}
        >
          Trash
        </Button>
      </div>

      {/* Filter & Fulltext Search Card */}
      {tab === "active" && (
        <Card className="mb-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[hsl(var(--border))] pb-2">
            <div className="flex items-center gap-1.5">
              <Button
                size="sm"
                variant={searchMode === "structured" ? "primary" : "secondary"}
                aria-pressed={searchMode === "structured"}
                onClick={() => setSearchMode("structured")}
              >
                Structured Filters
              </Button>
              <Button
                size="sm"
                variant={searchMode === "fulltext" ? "primary" : "secondary"}
                aria-pressed={isFulltext}
                onClick={() => setSearchMode("fulltext")}
              >
                Full-text Search
              </Button>
            </div>
            <Link href={`/w/${wid}/collections/${cid}/queries`} className="text-sm font-medium hover:underline">
              Saved queries
            </Link>
          </div>
          {isFulltext ? (
            <FullTextSearchBar
              status={searchStatusQuery.data}
              resultStatus={fulltextQuery.data?.index_status}
              statusLoading={searchStatusQuery.isPending}
              statusError={searchStatusQuery.isError}
              onRefreshStatus={() => searchStatusQuery.refetch()}
              isSearching={fulltextQuery.isFetching}
              text={fulltextDraft}
              onTextChange={setFulltextDraft}
              onSearch={(q) => {
                if (q === fulltextQueryText && fulltextCursorStack.length === 1) {
                  void fulltextQuery.refetch();
                }
                setFulltextQueryText(q);
                setFulltextCursorStack([null]);
              }}
              onClear={() => {
                setFulltextDraft("");
                setFulltextQueryText(null);
                setFulltextCursorStack([null]);
              }}
            />
          ) : (
            <>
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
                      setFilterError(null);
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
                          updateRow(idx, { op, value: op === "exists" ? "true" : "" });
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
                      ) : row.op === "between" ? (
                        <div className="flex min-w-0 flex-wrap gap-2">
                          {(["From", "To"] as const).map((label, bound) => {
                            const values = row.value.split(",");
                            const value = values[bound] ?? "";
                            return (
                              <Input
                                key={label}
                                aria-label={`${label} value for condition ${idx + 1}`}
                                type={type === "datetime" ? "datetime-local" : type === "number" ? "number" : "text"}
                                step="any"
                                className="w-auto max-w-full"
                                placeholder={label}
                                value={type === "datetime" && value ? toLocalInput(value) : value}
                                onChange={(e) => {
                                  const next = e.target.value;
                                  values[bound] = type === "datetime" && next ? new Date(next).toISOString() : next;
                                  updateRow(idx, { value: values.join(",") });
                                }}
                              />
                            );
                          })}
                        </div>
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
                          step="any"
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
                {filterError && <p className="text-sm text-[hsl(var(--destructive))]" role="alert">{filterError}</p>}
                {/* Enables Enter-to-apply from any input */}
                <button type="submit" hidden aria-hidden tabIndex={-1} />
              </form>
            </>
          )}
        </Card>
      )}

      <div className="mb-2 flex flex-wrap items-center gap-2">
        <div className="w-full min-w-0 text-sm font-medium sm:w-auto sm:flex-1" aria-live="polite">
          {isFulltext
            ? fulltextQueryText && <span className="break-words">Results for <strong>{fulltextQueryText}</strong></span>
            : tab === "trash" ? "Deleted records" : "Records"}
        </div>
        <FieldVisibilityPicker
          availablePaths={discoveredPaths}
          visibleColumns={visibleColumns}
          onChange={handleColumnsChange}
        />
        <Link
          href={`/w/${wid}/collections/${cid}/schema`}
          className="inline-flex h-8 items-center rounded-md border border-[hsl(var(--border))] px-3 text-xs font-medium hover:bg-[hsl(var(--muted))]"
        >
          Schema (v{colQuery.data?.schema_version ?? 1})
        </Link>
        {(canExport || canImport || canDeleteCollection) && (
          <div
            className="relative"
            onBlur={(e) => {
              if (!e.currentTarget.contains(e.relatedTarget)) setShowActions(false);
            }}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.currentTarget.querySelector("button")?.focus();
                setShowActions(false);
              }
            }}
          >
            <Button size="sm" variant="secondary" aria-expanded={showActions} onClick={() => setShowActions(!showActions)}>
              Actions
              <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
            </Button>
            {showActions && (
              <div className="absolute right-0 z-30 mt-1 flex w-40 flex-col rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--surface-elevated))] p-1 shadow-lg">
                {canExport && (
                  <Button size="sm" variant="ghost" className="justify-start" onClick={() => {
                    setShowActions(false);
                    exportMutation.mutate("csv");
                  }}>
                    <Download className="h-3.5 w-3.5" />
                    Export CSV
                  </Button>
                )}
                {canImport && (
                  <Button size="sm" variant="ghost" className="justify-start" onClick={() => {
                    setShowActions(false);
                    setOpenImport(true);
                  }}>
                    <Upload className="h-3.5 w-3.5" />
                    Import
                  </Button>
                )}
                {canDeleteCollection && (
                  <Button size="sm" variant="ghost" className="justify-start text-[hsl(var(--destructive))]" onClick={() => {
                    setShowActions(false);
                    setOpenDeleteCollection(true);
                  }}>
                    <Trash2 className="h-3.5 w-3.5" />
                    Delete collection
                  </Button>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Records Table */}
      {currentQuery.isLoading && <SkeletonTable rows={6} />}
      {currentQuery.isError && (!isFulltext || fulltextQueryText) && (
        <ErrorState error={currentQuery.error} onRetry={() => currentQuery.refetch()} />
      )}

      {currentQuery.isSuccess && activeRows.length === 0 && (
        <EmptyState
          title={isFulltext && currentQuery.data?.has_more
            ? "No available records on this page"
            : tab === "active" ? "No records match" : "Trash is empty"}
          description={isFulltext
            ? currentQuery.data?.has_more
              ? "Some indexed matches are no longer available. Continue to the next page."
              : "Try different words or check the index coverage above."
            : tab === "active"
              ? "Adjust the filters or add a record."
              : "Deleted records appear here within the retention window."}
        />
      )}

      {activeRows.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface-elevated))]">
          <table className="w-full border-separate border-spacing-0 text-left text-sm">
            <thead className="border-b border-[hsl(var(--border))] bg-[hsl(var(--surface))] text-xs uppercase text-[hsl(var(--muted-foreground))]">
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id}>
                  {hg.headers.map((header) => (
                    <th key={header.id} scope="col" className={`border-b border-[hsl(var(--border))] px-3 py-2.5 font-medium ${
                      header.column.id === "record" ? "sticky left-0 z-10 bg-[hsl(var(--surface))]" : ""
                    }`}>
                      {flexRender(header.column.columnDef.header, header.getContext())}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => (
                <tr key={row.id} className="group hover:bg-[hsl(var(--surface))]">
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className={`border-b border-[hsl(var(--border))] px-3 py-2 align-top ${
                      cell.column.id === "record"
                        ? "sticky left-0 z-10 w-px border-r bg-[hsl(var(--surface-elevated))] group-hover:bg-[hsl(var(--surface))]"
                        : "min-w-28 max-w-xs"
                    }`}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {isFulltext && fulltextQuery.data?.result_window_limited && (
        <p className="mt-3 text-sm text-[hsl(var(--muted-foreground))]">
          You reached the 1,000-match search limit. Narrow your search to find other records.
        </p>
      )}

      {/* Cursor Pagination Controls */}
      {(pageStack.length > 1 || currentQuery.data?.has_more) && (
        <div className="mt-4 flex items-center justify-between">
          <div className="text-xs text-[hsl(var(--muted-foreground))]">
            Page {pageStack.length} · {activeRows.length} records on this page
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
                !currentQuery.data?.has_more ||
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
          if (!updateMutation.isPending) setEditingRecord(null);
        }}
        title="Edit record"
      >
        {editingRecord && (
          <div className="space-y-3">
            <div className="flex items-center justify-between text-xs text-[hsl(var(--muted-foreground))]">
              <span className="break-all font-mono">{editingRecord.id} · v{editingRecord.version}</span>
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
                    setEditError(null);
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
              readOnly={!canEdit || updateMutation.isPending}
              value={editJson}
              onChange={(e) => {
                setEditJson(e.target.value);
                if (!conflictRecord) setEditError(null);
              }}
              className="max-h-[45dvh] w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3 font-mono text-xs"
            />
            {editError && <p className="text-sm text-[hsl(var(--destructive))]" role="alert">{editError}</p>}
            <div className="flex justify-end gap-2">
              <Button variant="secondary" disabled={updateMutation.isPending} onClick={() => setEditingRecord(null)}>
                Cancel
              </Button>
              {canEdit && (
                <Button
                  onClick={() => updateMutation.mutate()}
                  disabled={updateMutation.isPending || Boolean(conflictRecord)}
                >
                  {updateMutation.isPending ? "Saving…" : "Save changes"}
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
      {inspectedRecord && (
        <RecordDetailDrawer
          key={inspectedRecord.id}
          record={inspectedRecord}
          onClose={() => setInspectedRecord(null)}
          canEdit={canEdit}
          onEdit={openEditor}
          onCopyToast={(msg) => toast({ title: msg, variant: "success" })}
        />
      )}
    </AppShell>
  );
}
