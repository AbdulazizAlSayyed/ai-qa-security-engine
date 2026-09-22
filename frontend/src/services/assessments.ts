import { apiGet, apiPost } from "@/services/api";
import type { Assessment, Evidence } from "@/types/assessment";

const BASE = "/assessments";

export function listAssessments(limit = 25, signal?: AbortSignal): Promise<Assessment[]> {
  return apiGet<Assessment[]>(`${BASE}?limit=${limit}`, { signal });
}

export function getAssessment(id: string, signal?: AbortSignal): Promise<Assessment> {
  return apiGet<Assessment>(`${BASE}/${encodeURIComponent(id)}`, { signal });
}

export function getAssessmentEvidence(
  id: string,
  limit = 500,
  signal?: AbortSignal,
): Promise<Evidence[]> {
  return apiGet<Evidence[]>(`${BASE}/${encodeURIComponent(id)}/evidence?limit=${limit}`, {
    signal,
  });
}

/**
 * Run the whole pipeline: QA, then security, then normalization.
 *
 * Only a registered target id is sent - never a URL. Resolves once both
 * engines have finished, so expect tens of seconds; the assessment is
 * already visible (with its real current state) in the list meanwhile.
 */
export function startAssessment(targetId: string): Promise<Assessment> {
  return apiPost<Assessment>(BASE, { target_id: targetId }, { acceptStatuses: [201] });
}
