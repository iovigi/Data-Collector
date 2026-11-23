export interface ApiErrorDetail {
  path?: string;
  reason?: string;
}

export class ApiError extends Error {
  status: number;
  code: string;
  details: ApiErrorDetail[];
  requestId: string;

  constructor(params: {
    status: number;
    code: string;
    message: string;
    details?: ApiErrorDetail[];
    requestId?: string;
  }) {
    super(params.message);
    this.name = "ApiError";
    this.status = params.status;
    this.code = params.code;
    this.details = params.details ?? [];
    this.requestId = params.requestId ?? "req_unknown";
  }
}

export async function parseApiError(resp: Response): Promise<ApiError> {
  const reqIdHeader = resp.headers.get("X-Request-Id") ?? "req_unknown";
  try {
    const body = (await resp.json()) as {
      error?: {
        code?: string;
        message?: string;
        details?: ApiErrorDetail[];
        request_id?: string;
      };
    };
    if (body?.error) {
      return new ApiError({
        status: resp.status,
        code: body.error.code ?? "HTTP_ERROR",
        message: body.error.message ?? `Request failed (${resp.status})`,
        details: body.error.details ?? [],
        requestId: body.error.request_id ?? reqIdHeader,
      });
    }
  } catch {
    // non-JSON error
  }
  return new ApiError({
    status: resp.status,
    code: resp.status === 401 ? "UNAUTHENTICATED" : "HTTP_ERROR",
    message: `Request failed with status ${resp.status}`,
    requestId: reqIdHeader,
  });
}
