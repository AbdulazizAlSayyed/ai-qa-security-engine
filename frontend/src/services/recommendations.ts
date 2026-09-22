import { apiGet, apiPost } from "@/services/api";
import type { RecommendationsView } from "@/types/recommendations";

function path(assessmentId: string): string {
  return `/assessments/${encodeURIComponent(assessmentId)}/recommendations`;
}

/** The newest recommendation set, or the set generated from one AI analysis. */
export function getRecommendations(
  assessmentId: string,
  aiAnalysisId?: string | null,
  signal?: AbortSignal,
): Promise<RecommendationsView> {
  const query = aiAnalysisId ? `?ai_analysis_id=${encodeURIComponent(aiAnalysisId)}` : "";
  return apiGet<RecommendationsView>(`${path(assessmentId)}${query}`, { signal });
}

/**
 * Generate advisory recommendations. Only the assessment id is sent: the
 * backend loads issues, evidence and the AI analysis itself. Nothing is
 * applied or executed; a failed generation surfaces as an ApiError.
 */
export function generateRecommendations(assessmentId: string): Promise<RecommendationsView> {
  return apiPost<RecommendationsView>(path(assessmentId), {});
}
