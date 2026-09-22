import { Link } from "react-router-dom";

import StatusPill from "@/components/StatusPill";
import {
  ACTIVE_STATES,
  ASSESSMENT_LABEL,
  ASSESSMENT_TONE,
  formatDuration,
  formatTimestamp,
} from "@/lib/assessment";
import type { Assessment } from "@/types/assessment";

/**
 * Shared by the header and the rows so the columns always line up. From md
 * up the row keeps a minimum width and the list scrolls sideways instead of
 * squeezing the target column to nothing.
 */
export const ASSESSMENT_GRID =
  "grid grid-cols-2 items-center gap-x-3 gap-y-1 md:min-w-[53rem] md:grid-cols-[8.5rem_minmax(9rem,1fr)_9.5rem_4.5rem_5.5rem_6.5rem_4.5rem]";

export function AssessmentListHeader() {
  return (
    <div
      className={`${ASSESSMENT_GRID} hidden border-b border-slate-800 px-4 py-2 text-[11px] tracking-wide text-slate-500 uppercase md:grid`}
    >
      <span>Status</span>
      <span>Target</span>
      <span>Started</span>
      <span>Duration</span>
      <span>QA</span>
      <span>Security</span>
      <span className="text-right">Findings</span>
    </div>
  );
}

function stageNote(assessment: Assessment): string | null {
  if (assessment.qa_status === "failed") return "QA could not execute";
  if (assessment.security_status === "failed") return "Security could not execute";
  return null;
}

export default function AssessmentRow({ assessment }: { assessment: Assessment }) {
  const { summary } = assessment;
  const active = ACTIVE_STATES.has(assessment.status);
  const note = stageNote(assessment);

  return (
    <Link
      to={`/assessments/${assessment.id}`}
      className={`${ASSESSMENT_GRID} border-b border-slate-800/70 px-4 py-3 text-sm transition-colors last:border-b-0 hover:bg-slate-800/40`}
    >
      <span>
        <StatusPill tone={ASSESSMENT_TONE[assessment.status]} pulse={active}>
          {ASSESSMENT_LABEL[assessment.status]}
        </StatusPill>
      </span>

      <span className="min-w-0">
        <span className="block truncate font-medium text-slate-100">
          {assessment.target_name}
        </span>
        <span className="block truncate font-mono text-xs text-slate-500">
          {note ?? assessment.target_base_url}
        </span>
      </span>

      <span className="text-xs text-slate-400">{formatTimestamp(assessment.started_at)}</span>
      <span className="text-xs text-slate-400">
        {active ? "…" : formatDuration(assessment.duration_ms)}
      </span>

      {/* Counts are written once, at the end of a run; until then show nothing. */}
      <span className="text-slate-300">
        {active ? (
          <span className="text-slate-500">—</span>
        ) : (
          <>
            {summary.qa.passed}/{summary.qa.total}
            <span className="ml-1 text-xs text-slate-500">passed</span>
          </>
        )}
      </span>

      <span className="text-slate-300">
        {active ? (
          <span className="text-slate-500">—</span>
        ) : (
          <>
            {summary.security.total}
            <span className="ml-1 text-xs text-slate-500">
              {summary.security.high > 0 ? `${summary.security.high} high` : "findings"}
            </span>
          </>
        )}
      </span>

      <span
        className={`text-right font-mono ${summary.total_findings > 0 ? "text-amber-300" : "text-slate-300"}`}
      >
        {active ? "—" : summary.total_findings}
      </span>
    </Link>
  );
}
