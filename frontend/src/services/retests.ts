import { apiGet, apiPost } from "@/services/api";
import type { Retest } from "@/types/retests";

function base(assessmentId: string): string {
  return `/assessments/${encodeURIComponent(assessmentId)}`;
}

/**
 * Execute the stored retest specification of one recommendation. Only the
 * recommendation reference (and its set) is sent - the backend loads the
 * specification and decides the scope. A failed execution is recorded
 * server-side and surfaces here as an ApiError (HTTP 502).
 */
export function runRetest(
  assessmentId: string,
  recommendationId: string,
  aiAnalysisId?: string | null,
): Promise<Retest> {
  const query = aiAnalysisId ? `?ai_analysis_id=${encodeURIComponent(aiAnalysisId)}` : "";
  return apiPost<Retest>(
    `${base(assessmentId)}/recommendations/${encodeURIComponent(recommendationId)}/retest${query}`,
    {},
    { acceptStatuses: [201] },
  );
}

/** Retest history of an assessment, newest first. */
export function listRetests(assessmentId: string, signal?: AbortSignal): Promise<Retest[]> {
  return apiGet<Retest[]>(`${base(assessmentId)}/retests?limit=500`, { signal });
}

export function getRetest(assessmentId: string, retestId: string, signal?: AbortSignal): Promise<Retest> {
  return apiGet<Retest>(`${base(assessmentId)}/retests/${encodeURIComponent(retestId)}`, { signal });
}
