/**
 * Minimal HTTP client for the FastAPI backend.
 *
 * Every service module goes through this so there is one place that knows
 * about the base URL, JSON handling and what "the backend is not running"
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

export async function apiGet<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { signal, acceptStatuses = [200] } = options;
  const url = `${config.apiBaseUrl}${path}`;

  let response: Response;
  try {
    response = await fetch(url, { headers: { Accept: "application/json" }, signal });
  } catch (cause) {
    if (signal?.aborted) throw cause;
    throw new ApiUnreachableError(
      `No response from ${config.apiBaseUrl}. Is the backend running on that address?`,
    );
  }

  if (!acceptStatuses.includes(response.status)) {
    throw new ApiError(`${path} returned HTTP ${response.status}`, response.status);
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError(`${path} did not return valid JSON`, response.status);
  }
}
