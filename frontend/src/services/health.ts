import { apiGet } from "@/services/api";
import type { HealthResponse } from "@/types/health";

/**
 * Fetch backend health.
 *
 * 503 is accepted alongside 200: a degraded backend still returns a full
 * health body explaining why MongoDB is unreachable, and showing that beats
 * showing a generic network error.
 */
export function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return apiGet<HealthResponse>("/health", { signal, acceptStatuses: [200, 503] });
}
