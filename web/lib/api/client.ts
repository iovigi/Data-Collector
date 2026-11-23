import { parseApiError } from "./errors";

function readCookie(name: string): string {
  if (typeof document === "undefined") return "";
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.split("=").slice(1).join("=")) : "";
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  rawBody?: BodyInit;
  contentType?: string;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export async function apiFetch<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method ?? "GET";
  const headers: Record<string, string> = { ...(opts.headers ?? {}) };

  if (method !== "GET") {
    const csrf = readCookie("dc_csrf");
    if (csrf) {
      headers["X-CSRF-Token"] = csrf;
    }
  }

  let body: BodyInit | undefined = opts.rawBody;
  if (opts.body !== undefined) {
    headers["Content-Type"] = opts.contentType ?? "application/json";
    body = JSON.stringify(opts.body);
  } else if (opts.contentType) {
    headers["Content-Type"] = opts.contentType;
  }

  const cleanPath = path.replace(/^\/+/, "");
  const resp = await fetch(`/api/backend/${cleanPath}`, {
    method,
    headers,
    body,
    credentials: "same-origin",
    signal: opts.signal,
  });

  if (!resp.ok) {
    throw await parseApiError(resp);
  }

  if (resp.status === 204) {
    return undefined as T;
  }
  const ctype = resp.headers.get("content-type") ?? "";
  if (ctype.includes("application/json")) {
    return (await resp.json()) as T;
  }
  return (await resp.text()) as unknown as T;
}

export async function apiAuthPost<T>(
  endpoint: "/api/auth/login" | "/api/auth/logout" | "/api/auth/refresh",
  body?: unknown
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const csrf = readCookie("dc_csrf");
  if (csrf) {
    headers["X-CSRF-Token"] = csrf;
  }
  const resp = await fetch(endpoint, {
    method: "POST",
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  });
  if (!resp.ok) {
    throw await parseApiError(resp);
  }
  return (await resp.json()) as T;
}
