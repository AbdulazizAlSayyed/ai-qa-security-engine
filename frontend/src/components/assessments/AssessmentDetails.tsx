import type { ReactNode } from "react";

import StatusPill from "@/components/StatusPill";
import {
  ACTIVE_STATES,
  ASSESSMENT_LABEL,
  ASSESSMENT_TONE,
  PIPELINE,
  STAGE_LABEL,
  STAGE_TONE,
  formatDuration,
  formatTime,
  formatTimestamp,
} from "@/lib/assessment";
import type { Assessment, StageStatus } from "@/types/assessment";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <p className="text-xs tracking-wide text-slate-500 uppercase">{label}</p>
      <div className="mt-0.5 text-sm break-words text-slate-200">{children}</div>
    </div>
  );
}

function Count({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div>
      <p className={`font-mono text-lg ${tone ?? "text-slate-100"}`}>{value}</p>
      <p className="text-[11px] text-slate-500">{label}</p>
    </div>
  );
}

interface StageCardProps {
  title: string;
  status: StageStatus;
  runId: string | null;
  runStatus: string | null;
  error: string | null;
  showCounts: boolean;
  children: ReactNode;
}

function StageCard({ title, status, runId, runStatus, error, showCounts, children }: StageCardProps) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium tracking-wide text-slate-400 uppercase">{title}</p>
        <StatusPill tone={STAGE_TONE[status]} pulse={status === "running"}>
          {STAGE_LABEL[status]}
        </StatusPill>
      </div>

      {showCounts ? <div className="mt-3 grid grid-cols-5 gap-2">{children}</div> : null}

      {error ? (
        <p className="mt-3 rounded-md bg-rose-500/5 px-2 py-1.5 font-mono text-[11px] break-all text-rose-200/90">
          {error}
        </p>
      ) : null}

      <p className="mt-3 font-mono text-[11px] break-all text-slate-500">
        run {runId ?? "—"}
        {runStatus ? ` · tool verdict: ${runStatus}` : ""}
      </p>
    </div>
  );
}

export default function AssessmentDetails({ assessment }: { assessment: Assessment }) {
  const { summary } = assessment;
  const active = ACTIVE_STATES.has(assessment.status);
  const reached = new Set(assessment.state_history.map((t) => t.state));

  return (
    <div className="flex flex-col gap-6">
      <section className="grid gap-4 rounded-xl border border-slate-800 bg-slate-900/60 p-5 sm:grid-cols-2 xl:grid-cols-4">
        <Field label="Status">
          <StatusPill tone={ASSESSMENT_TONE[assessment.status]} pulse={active}>
            {ASSESSMENT_LABEL[assessment.status]}
          </StatusPill>
        </Field>
        <Field label="Started">{formatTimestamp(assessment.started_at)}</Field>
        <Field label="Duration">{active ? "running…" : formatDuration(assessment.duration_ms)}</Field>
        <Field label="Findings">
          {active ? "—" : (
            <span className={summary.total_findings > 0 ? "text-amber-300" : ""}>
              {summary.total_findings}
              <span className="ml-1 text-xs text-slate-500">
                ({summary.qa.failed} QA failed + {summary.security.total} security)
              </span>
            </span>
          )}
        </Field>
        <Field label="Target">{assessment.target_name}</Field>
        <Field label="Base URL">
          <span className="font-mono">{assessment.target_base_url}</span>
        </Field>
        <Field label="API URL">
          <span className="font-mono">{assessment.target_api_url ?? "—"}</span>
        </Field>
        <Field label="Type">{assessment.target_type}</Field>
      </section>

      {assessment.error ? (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 px-4 py-3">
          <p className="text-sm font-medium text-rose-200">Assessment failed</p>
          <p className="mt-1 font-mono text-xs break-all text-rose-200/80">{assessment.error}</p>
        </div>
      ) : null}

      {assessment.partial ? (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm text-amber-200">
          Partial execution: one engine could not run, so its evidence is absent rather than
          invented. See the stage cards below for the reason.
        </div>
      ) : null}

      <section>
        <h2 className="text-sm font-semibold text-slate-200">Pipeline</h2>
        <ol className="mt-2 flex flex-wrap items-center gap-1.5">
          {PIPELINE.map((state, index) => {
            const isCurrent = assessment.status === state;
            const isReached = reached.has(state);
            return (
              <li key={state} className="flex items-center gap-1.5">
                <span
                  className={`rounded-md px-2 py-0.5 font-mono text-[11px] ${
                    isCurrent && active
                      ? "animate-pulse bg-sky-500/15 text-sky-300"
                      : isReached
                        ? "bg-slate-800/70 text-slate-200"
                        : "bg-slate-900 text-slate-600"
                  }`}
                >
                  {state}
                </span>
                {index < PIPELINE.length - 1 ? <span className="text-slate-700">&rarr;</span> : null}
              </li>
            );
          })}
          {assessment.status === "failed" ? (
            <li className="flex items-center gap-1.5">
              <span className="text-slate-700">&rarr;</span>
              <span className="rounded-md bg-rose-500/10 px-2 py-0.5 font-mono text-[11px] text-rose-300">
                failed
              </span>
            </li>
          ) : null}
        </ol>

        <ol className="mt-3 flex flex-col gap-1 rounded-xl border border-slate-800 bg-slate-950/40 p-3 text-xs">
          {assessment.state_history.map((transition, index) => (
            <li key={`${transition.state}-${index}`} className="grid grid-cols-[6rem_9rem_1fr] gap-2">
              <span className="font-mono text-slate-500">{formatTime(transition.timestamp)}</span>
              <span className="font-mono text-slate-300">{transition.state}</span>
              <span className="text-slate-400">{transition.message ?? ""}</span>
            </li>
          ))}
        </ol>
      </section>

      <section className="grid gap-3 md:grid-cols-2">
        <StageCard
          title="QA engine · Playwright"
          status={assessment.qa_status}
          runId={assessment.qa_run_id}
          runStatus={assessment.qa_run_status}
          error={assessment.qa_error}
          showCounts={!active}
        >
          <Count label="total" value={summary.qa.total} />
          <Count label="passed" value={summary.qa.passed} tone="text-emerald-300" />
          <Count label="failed" value={summary.qa.failed} tone={summary.qa.failed ? "text-rose-300" : undefined} />
          <Count label="skipped" value={summary.qa.skipped} />
          <Count label="error" value={summary.qa.error} tone={summary.qa.error ? "text-amber-300" : undefined} />
        </StageCard>

        <StageCard
          title="Security engine · ZAP / API / Semgrep"
          status={assessment.security_status}
          runId={assessment.security_run_id}
          runStatus={assessment.security_run_status}
          error={assessment.security_error}
          showCounts={!active}
        >
          <Count label="total" value={summary.security.total} />
          <Count label="high" value={summary.security.high} tone={summary.security.high ? "text-rose-300" : undefined} />
          <Count label="medium" value={summary.security.medium} tone={summary.security.medium ? "text-amber-300" : undefined} />
          <Count label="low" value={summary.security.low} />
          <Count label="info" value={summary.security.informational} />
        </StageCard>
      </section>

      {assessment.security_coverage.length > 0 ? (
        <section>
          <h2 className="text-sm font-semibold text-slate-200">Security coverage</h2>
          <ul className="mt-2 flex flex-wrap gap-2">
            {assessment.security_coverage.map((item) => (
              <li
                key={item.source}
                className="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-1.5 text-xs"
                title={item.detail ?? undefined}
              >
                <span className="font-mono text-slate-200">{item.source}</span>
                <span
                  className={`ml-2 ${
                    item.status === "completed"
                      ? "text-emerald-300"
                      : item.status === "failed"
                        ? "text-rose-300"
                        : "text-slate-500"
                  }`}
                >
                  {item.status}
                </span>
                {item.detail ? <span className="ml-2 text-slate-500">{item.detail}</span> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
