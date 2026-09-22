import { apiGet, apiPost } from "@/services/api";
import type { CorrelationGroup, CorrelationRun, Issue, IssueType, Priority } from "@/types/issues";

function base(assessmentId: string): string {
  return `/assessments/${encodeURIComponent(assessmentId)}`;
}

export interface IssueFilters {
  type?: IssueType;
  priority?: Priority;
}

/** Prioritized issues: P1 first, then score, then issue number. */
export function getIssues(
  assessmentId: string,
  filters: IssueFilters = {},
  signal?: AbortSignal,
): Promise<Issue[]> {
  const params = new URLSearchParams({ limit: "500" });
  if (filters.type) params.set("type", filters.type);
  if (filters.priority) params.set("priority", filters.priority);
  return apiGet<Issue[]>(`${base(assessmentId)}/issues?${params}`, { signal });
}

export function getIssue(assessmentId: string, issueId: string, signal?: AbortSignal): Promise<Issue> {
  return apiGet<Issue>(`${base(assessmentId)}/issues/${encodeURIComponent(issueId)}`, { signal });
}

export function getCorrelationGroups(
  assessmentId: string,
  signal?: AbortSignal,
): Promise<CorrelationGroup[]> {
  return apiGet<CorrelationGroup[]>(`${base(assessmentId)}/correlation-groups`, { signal });
}

/**
 * Correlate and prioritize the stored evidence. Deterministic and idempotent:
 * running it again updates the same issues. No AI provider is called.
 */
export function runCorrelation(assessmentId: string): Promise<CorrelationRun> {
  return apiPost<CorrelationRun>(`${base(assessmentId)}/correlation`, {});
}
