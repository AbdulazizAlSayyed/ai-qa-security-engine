import type { Tone } from "@/components/StatusPill";
import type {
  AssessmentState,
  EvidenceStatus,
  StageStatus,
} from "@/types/assessment";
import type { Target } from "@/types/target";

/**
 * Only orchestration breaking is bad. An assessment full of failures and
 * findings is a successful assessment - that is the output.
 */
export const ASSESSMENT_TONE: Record<AssessmentState, Tone> = {
  created: "neutral",
  running: "neutral",
  qa_running: "neutral",
  security_running: "neutral",
  normalizing: "neutral",
  analyzing: "neutral",
  completed: "positive",
  failed: "negative",
};

export const ASSESSMENT_LABEL: Record<AssessmentState, string> = {
  created: "Created",
  running: "Running",
  qa_running: "QA running",
  security_running: "Security running",
  normalizing: "Normalizing",
  analyzing: "Analyzing",
  completed: "Completed",
  failed: "Failed",
};

/** States the pipeline passes through while it is still working. */
export const ACTIVE_STATES: ReadonlySet<AssessmentState> = new Set([
  "created",
  "running",
  "qa_running",
  "security_running",
  "normalizing",
]);

/** The Phase 4 happy path, for drawing the pipeline. */
export const PIPELINE: AssessmentState[] = [
  "created",
  "running",
  "qa_running",
  "security_running",
  "normalizing",
  "completed",
];

export const STAGE_TONE: Record<StageStatus, Tone> = {
  pending: "neutral",
  running: "neutral",
  completed: "positive",
  failed: "negative",
};

export const STAGE_LABEL: Record<StageStatus, string> = {
  pending: "Pending",
  running: "Running",
  completed: "Executed",
  failed: "Could not execute",
};

export const EVIDENCE_TONE: Record<EvidenceStatus, Tone> = {
  passed: "positive",
  failed: "negative",
  skipped: "neutral",
  error: "warning",
  observed: "neutral",
};

export const EVIDENCE_LABEL: Record<EvidenceStatus, string> = {
  passed: "Passed",
  failed: "Failed",
  skipped: "Skipped",
  error: "Error",
  observed: "Observed",
};

/**
 * A full assessment drives the QA engine through a real browser, so the
 * target must expose a UI. API-only targets are not assessable yet.
 * Shared by every page that can start an assessment.
 */
export const ASSESSABLE_TARGET_TYPES: ReadonlySet<string> = new Set([
  "web_application",
  "web_and_api",
]);

export function assessableTargets(targets: Target[] | null): Target[] {
  return (targets ?? []).filter(
    (target) => target.enabled && ASSESSABLE_TARGET_TYPES.has(target.type) && target.base_url,
  );
}

/** The short reference the AI cites. Same rule as app/engines/ai/context.py. */
export function evidenceRef(sequence: number): string {
  return `EV-${String(sequence + 1).padStart(3, "0")}`;
}

export function formatDuration(ms: number | null): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

export function formatTimestamp(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

export function formatTime(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleTimeString();
}
