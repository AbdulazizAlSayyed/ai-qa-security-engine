import { apiGet, apiPost } from "@/services/api";
import type { AIAnalysis, AIAnalysisView } from "@/types/aiAnalysis";

function path(assessmentId: string): string {
  return `/assessments/${encodeURIComponent(assessmentId)}/ai-analysis`;
}

export function getAIAnalysis(assessmentId: string, signal?: AbortSignal): Promise<AIAnalysisView> {
  return apiGet<AIAnalysisView>(path(assessmentId), { signal });
}

export function getAIAnalysisHistory(
  assessmentId: string,
  limit = 20,
  signal?: AbortSignal,
): Promise<AIAnalysis[]> {
  return apiGet<AIAnalysis[]>(`${path(assessmentId)}/history?limit=${limit}`, { signal });
}

/**
 * Ask the backend to analyse this assessment's stored evidence.
 *
 * Nothing is sent but the assessment id: the backend loads the evidence
 * itself. Resolves with the completed analysis; a failed analysis is still
 * recorded server-side and surfaces here as an ApiError (502 / 503).
 */
export function startAIAnalysis(assessmentId: string): Promise<AIAnalysis> {
  return apiPost<AIAnalysis>(path(assessmentId), {}, { acceptStatuses: [201] });
}
