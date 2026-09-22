import { config } from "@/lib/config";
import { apiGet, apiPost } from "@/services/api";
import type { Report } from "@/types/reports";

function base(assessmentId: string): string {
  return `/assessments/${encodeURIComponent(assessmentId)}/reports`;
}

/**
 * Generate a report. Nothing but the assessment id is sent: the backend loads
 * every source record, audits traceability and renders HTML + PDF. Unchanged
 * data returns the existing report (200, reused) instead of a duplicate.
 */
export function generateReport(assessmentId: string): Promise<Report> {
  return apiPost<Report>(base(assessmentId), {}, { acceptStatuses: [200, 201] });
}

/** Reports of an assessment, newest first. */
export function listReports(assessmentId: string, signal?: AbortSignal): Promise<Report[]> {
  return apiGet<Report[]>(`${base(assessmentId)}?limit=100`, { signal });
}

/** Direct links to the stored files (served by the backend, SHA-256 checked). */
export function reportFileUrl(assessmentId: string, reportId: string, format: "html" | "pdf"): string {
  return `${config.apiBaseUrl}${base(assessmentId)}/${encodeURIComponent(reportId)}/${format}`;
}
