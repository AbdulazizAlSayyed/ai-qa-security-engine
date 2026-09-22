import { apiGet, apiPost } from "@/services/api";
import type { QaRun } from "@/types/qa";

const BASE = "/qa/runs";

export function listQaRuns(limit = 50, signal?: AbortSignal): Promise<QaRun[]> {
  return apiGet<QaRun[]>(`${BASE}?limit=${limit}`, { signal });
}

export function getQaRun(id: string, signal?: AbortSignal): Promise<QaRun> {
  return apiGet<QaRun>(`${BASE}/${id}`, { signal });
}

/**
 * Start a QA run. Resolves once the browser has finished driving the target,
 * so expect this to take seconds rather than milliseconds.
 *
 * A run whose status is "failed" or "error" still resolves successfully -
 * that is a result about the target, not a transport failure.
 */
export function startQaRun(targetId: string): Promise<QaRun> {
  return apiPost<QaRun>(BASE, { target_id: targetId }, { acceptStatuses: [201] });
}
