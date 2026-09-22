/**
 * Minimal HTTP client for the FastAPI backend.
 *
 * Every service module goes through this so there is one place that knows
 * about the base URL, JSON handling, and what "the backend is not running"
 * looks like to a user.
 */

import { config } from "@/lib/config";

export class ApiError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Thrown when the request never reached the server at all. */
export class ApiUnreachableError extends ApiError {
  constructor(message: string) {
    super(message);
    this.name = "ApiUnreachableError";
  }
}

type HttpMethod = "GET" | "POST" | "PATCH" | "DELETE";

interface RequestOptions {
  signal?: AbortSignal;
  /**
   * Status codes to treat as a successful, parseable response.
   *
   * /health deliberately answers 503 when MongoDB is down, and that body is
   * exactly what the dashboard needs to display, so the caller opts in.
   */
  acceptStatuses?: number[];
}

interface ValidationItem {
  loc?: unknown[];
  msg?: string;
}

/**
 * Turn a FastAPI error body into something worth showing a user.
 *
 * FastAPI answers `{"detail": "message"}` for raised errors and
 * `{"detail": [{loc, msg, ...}]}` for request validation failures. Showing
 * "HTTP 422" instead of "name: String should have at least 1 character"
 * would make the form useless.
 */
function describeFailure(status: number, payload: unknown, path: string): string {
  const fallback = `${path} returned HTTP ${status}`;

  if (payload === null || typeof payload !== "object" || !("detail" in payload)) {
    return fallback;
  }

  const detail = (payload as { detail: unknown }).detail;

  if (typeof detail === "string" && detail.trim().length > 0) {
    return detail;
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map((entry) => {
        if (entry === null || typeof entry !== "object") return String(entry);
        const item = entry as ValidationItem;
        const field = Array.isArray(item.loc)
          ? item.loc.filter((part) => part !== "body").join(".")
          : "";
        const message = item.msg ?? "is invalid";
        return field ? `${field}: ${message}` : message;
      })
      .filter((message) => message.length > 0);

    if (messages.length > 0) return messages.join("; ");
  }

  return fallback;
}

async function apiRequest<T>(
  method: HttpMethod,
  path: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<T> {
  const { signal, acceptStatuses = [200] } = options;
  const url = `${config.apiBaseUrl}${path}`;

  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      signal,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (cause) {
    if (signal?.aborted) throw cause;
    throw new ApiUnreachableError(
      `No response from ${config.apiBaseUrl}. Is the backend running on that address?`,
    );
  }

  if (!acceptStatuses.includes(response.status)) {
    const payload = await response.json().catch(() => null);
    throw new ApiError(describeFailure(response.status, payload, path), response.status);
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError(`${path} did not return valid JSON`, response.status);
  }
}

export function apiGet<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return apiRequest<T>("GET", path, undefined, options);
}

export function apiPost<T>(
  path: string,
  body: unknown,
  options: RequestOptions = {},
): Promise<T> {
  return apiRequest<T>("POST", path, body, options);
}

export function apiPatch<T>(
  path: string,
  body: unknown,
  options: RequestOptions = {},
): Promise<T> {
  return apiRequest<T>("PATCH", path, body, options);
}

export function apiDelete<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return apiRequest<T>("DELETE", path, undefined, options);
}
