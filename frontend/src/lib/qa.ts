import type { Tone } from "@/components/StatusPill";
import type { QaStatus } from "@/types/qa";

/**
 * "error" is amber rather than red on purpose: it means the platform could
 * not run the check, which is a different problem from the target failing.
 */
export const QA_STATUS_TONE: Record<QaStatus, Tone> = {
  passed: "positive",
  failed: "negative",
  error: "warning",
};

export const QA_STATUS_LABEL: Record<QaStatus, string> = {
  passed: "Passed",
  failed: "Failed",
  error: "Engine error",
};

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

export function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

export function countByStatus(statuses: QaStatus[]): Record<QaStatus, number> {
  const counts: Record<QaStatus, number> = { passed: 0, failed: 0, error: 0 };
  for (const status of statuses) counts[status] += 1;
  return counts;
}
