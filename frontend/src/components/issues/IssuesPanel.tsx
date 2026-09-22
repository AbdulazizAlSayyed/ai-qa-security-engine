import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";

import StatusPill, { type Tone } from "@/components/StatusPill";
import IssueDetails from "@/components/issues/IssueDetails";
import PriorityBadge from "@/components/issues/PriorityBadge";
import { RULE_LABEL } from "@/components/issues/rules";
import SeverityBadge from "@/components/security/SeverityBadge";
import { formatTimestamp } from "@/lib/assessment";
import { getIssues, runCorrelation } from "@/services/issues";
import type { Assessment, Evidence } from "@/types/assessment";
import { PRIORITIES, type Issue, type Priority } from "@/types/issues";

interface IssuesPanelProps {
  assessment: Assessment;
  evidenceById: Map<string, Evidence>;
  onShowEvidence: (evidenceId: string) => void;
  /** Called after a run so the page re-reads the assessment's summary. */
  onProcessed: () => void;
  /** Open and scroll to this issue (e.g. from a recommendation); nonce re-triggers. */
  focusIssueId?: string | null;
  focusNonce?: number;
}

type Filter = "all" | "security" | "qa" | Priority;

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "security", label: "Security" },
  { value: "qa", label: "QA" },
  ...PRIORITIES.map((p) => ({ value: p, label: p })),
];

const STATUS_TONE: Record<string, Tone> = {
  running: "neutral",
  completed: "positive",
  failed: "negative",
};

function matches(issue: Issue, filter: Filter): boolean {
  if (filter === "all") return true;
  if (filter === "security" || filter === "qa") return issue.type === filter;
  return issue.priority === filter;
}

export default function IssuesPanel({
  assessment,
  evidenceById,
  onShowEvidence,
  onProcessed,
  focusIssueId = null,
  focusNonce = 0,
}: IssuesPanelProps) {
  const [issues, setIssues] = useState<Issue[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");
  const [openId, setOpenId] = useState<string | null>(null);
  const inFlight = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!focusIssueId) return;
    setFilter("all");
    setOpenId(focusIssueId);
    const timer = window.setTimeout(() => {
      document
        .getElementById(`issue-row-${focusIssueId}`)
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 50);
    return () => window.clearTimeout(timer);
  }, [focusIssueId, focusNonce]);

  const load = useCallback(async () => {
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;
    try {
      const loaded = await getIssues(assessment.id, {}, controller.signal);
      if (controller.signal.aborted) return;
      setIssues(loaded);
      setLoadError(null);
    } catch (caught) {
      if (controller.signal.aborted) return;
      setLoadError(caught instanceof Error ? caught.message : "Unexpected error");
    }
  }, [assessment.id]);

  useEffect(() => {
    void load();
    return () => inFlight.current?.abort();
  }, [load]);

  const handleRun = useCallback(async () => {
    setRunning(true);
    setRunError(null);
    try {
      const result = await runCorrelation(assessment.id);
      setIssues(result.issues);
    } catch (caught) {
      setRunError(caught instanceof Error ? caught.message : "Correlation could not run.");
      await load();
    } finally {
      setRunning(false);
      onProcessed();
    }
  }, [assessment.id, load, onProcessed]);

  const visible = useMemo(() => (issues ?? []).filter((i) => matches(i, filter)), [issues, filter]);
  const counts = useMemo(() => {
    const result: Record<Filter, number> = { all: 0, security: 0, qa: 0, P1: 0, P2: 0, P3: 0, P4: 0 };
    for (const issue of issues ?? []) {
      result.all += 1;
      result[issue.type] += 1;
      result[issue.priority] += 1;
    }
    return result;
  }, [issues]);

  const summary = assessment.correlation;
  const eligible = assessment.status === "completed";
  const status = running ? "running" : summary?.status;
  const staleAi =
    summary?.status === "completed" &&
    assessment.ai_analysis_status === "completed" &&
    assessment.ai_analysis_id !== null &&
    summary.ai_analysis_id !== assessment.ai_analysis_id;

  return (
    <section
      id="prioritized-issues"
      className="scroll-mt-6 rounded-xl border border-slate-800 bg-slate-900/60 p-5"
      aria-label="Prioritized Issues"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold text-slate-100">Prioritized Issues</h2>
            {status ? (
              <StatusPill tone={STATUS_TONE[status] ?? "neutral"} pulse={status === "running"}>
                {status === "running"
                  ? "Correlating"
                  : status === "completed"
                    ? "Correlated"
                    : "Correlation failed"}
              </StatusPill>
            ) : (
              <StatusPill tone="neutral">Not correlated</StatusPill>
            )}
          </div>
          <p className="mt-1 max-w-2xl text-sm text-slate-400">
            Evidence describing the same underlying issue is grouped by explicit rules, then
            ranked by a documented score. No AI call is made; a completed AI analysis is only
            used as supporting data. Priority is derived and never replaces the tool severity.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void handleRun()}
          disabled={!eligible || running}
          title={eligible ? undefined : "Only a completed assessment can be correlated."}
          className="rounded-lg bg-sky-500 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {running ? "Correlating..." : summary ? "Re-run Correlation" : "Correlate & Prioritize"}
        </button>
      </div>

      {summary && summary.status !== "running" ? (
        <p className="mt-3 font-mono text-[11px] text-slate-500">
          {summary.evidence_considered} of {summary.evidence_total} evidence records correlated
          {Object.entries(summary.evidence_excluded).length
            ? ` (${Object.entries(summary.evidence_excluded)
                .map(([status, count]) => `${count} ${status}`)
                .join(", ")} not issues)`
            : ""}{" "}
          · {summary.group_count} groups · rules v{summary.correlation_version ?? "?"} · priority
          model v{summary.priority_model_version ?? "?"} ·{" "}
          {summary.ai_analysis_id
            ? `AI analysis ${summary.ai_analysis_id.slice(0, 8)}… used as support`
            : "no AI analysis used"}{" "}
          · {formatTimestamp(summary.completed_at)}
        </p>
      ) : null}

      {staleAi ? (
        <p className="mt-2 text-xs text-amber-300">
          A newer AI analysis exists. Re-run correlation to include it as supporting data.
        </p>
      ) : null}

      {summary?.status === "failed" && summary.error ? (
        <p role="alert" className="mt-3 text-sm text-rose-300">
          Last run failed: {summary.error}
        </p>
      ) : null}
      {runError ? (
        <p role="alert" className="mt-3 text-sm text-rose-300">
          {runError}
        </p>
      ) : null}
      {loadError ? (
        <p role="alert" className="mt-3 text-sm text-rose-300">
          Could not load issues: {loadError}
        </p>
      ) : null}

      {issues && issues.length > 0 ? (
        <>
          <div className="mt-4 flex flex-wrap gap-1" role="group" aria-label="Filter issues">
            {FILTERS.map(({ value, label }) => (
              <button
                key={value}
                type="button"
                onClick={() => setFilter(value)}
                aria-pressed={filter === value}
                className={`rounded-md px-2.5 py-1 text-xs transition-colors ${
                  filter === value
                    ? "bg-sky-500/15 text-sky-300"
                    : "text-slate-400 hover:bg-slate-800/60"
                }`}
              >
                {label} <span className="font-mono text-slate-500">{counts[value]}</span>
              </button>
            ))}
          </div>

          <div className="mt-3 overflow-x-auto rounded-xl border border-slate-800 bg-slate-950/40">
            <table className="w-full min-w-[64rem] text-left text-xs">
              <thead className="border-b border-slate-800 text-[11px] tracking-wide text-slate-500 uppercase">
                <tr>
                  <th className="px-3 py-2 font-medium">Issue</th>
                  <th className="px-3 py-2 font-medium">Priority</th>
                  <th className="px-3 py-2 font-medium">Type</th>
                  <th className="px-3 py-2 font-medium">Title</th>
                  <th className="px-3 py-2 font-medium">Tool severity</th>
                  <th className="px-3 py-2 font-medium">Component</th>
                  <th className="px-3 py-2 font-medium">Evidence</th>
                  <th className="px-3 py-2 font-medium">Sources</th>
                  <th className="px-3 py-2 font-medium">Correlation rule</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((issue) => {
                  const open = openId === issue.issue_id;
                  const [firstComponent, ...moreComponents] = issue.affected_components;
                  return (
                    <Fragment key={issue.issue_id}>
                      <tr
                        id={`issue-row-${issue.issue_id}`}
                        onClick={() => setOpenId(open ? null : issue.issue_id)}
                        className={`cursor-pointer border-b border-slate-800/60 align-top transition-colors hover:bg-slate-800/40 ${
                          open ? "bg-slate-800/30" : ""
                        }`}
                      >
                        <td className="px-3 py-2 whitespace-nowrap">
                          <button
                            type="button"
                            aria-expanded={open}
                            className="font-mono text-sky-300 hover:text-sky-200"
                          >
                            {issue.issue_id}
                          </button>
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap">
                          <PriorityBadge priority={issue.priority} score={issue.priority_score} />
                        </td>
                        <td className="px-3 py-2 text-slate-400">
                          {issue.type === "security" ? "Security" : "QA"}
                        </td>
                        <td className="min-w-48 max-w-72 px-3 py-2 text-slate-100">{issue.title}</td>
                        <td className="px-3 py-2">
                          {issue.tool_severity ? (
                            <SeverityBadge severity={issue.tool_severity} />
                          ) : (
                            <span className="text-slate-600">—</span>
                          )}
                        </td>
                        <td className="min-w-44 max-w-64 px-3 py-2 font-mono break-all text-slate-300">
                          {firstComponent}
                          {moreComponents.length ? (
                            <span className="text-slate-500"> +{moreComponents.length} more</span>
                          ) : null}
                        </td>
                        <td className="px-3 py-2 font-mono text-slate-300">{issue.evidence_count}</td>
                        <td className="px-3 py-2 font-mono text-slate-400">
                          {issue.sources.join(", ")}
                        </td>
                        <td className="px-3 py-2 text-slate-400">
                          {RULE_LABEL[issue.correlation_rule] ?? issue.correlation_rule}
                        </td>
                      </tr>
                      {open ? (
                        <tr className="border-b border-slate-800/60 bg-slate-950/50">
                          <td colSpan={9}>
                            <IssueDetails
                              issue={issue}
                              evidenceById={evidenceById}
                              onShowEvidence={onShowEvidence}
                            />
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
            {visible.length === 0 ? (
              <p className="p-6 text-center text-sm text-slate-500">No issues in this view.</p>
            ) : null}
          </div>
        </>
      ) : null}

      {issues && issues.length === 0 && !loadError ? (
        <p className="mt-4 text-sm text-slate-500">
          {summary?.status === "completed"
            ? "Correlation found nothing to report: every check passed or was skipped."
            : "No issues yet. Run correlation to group and prioritize this assessment's evidence."}
        </p>
      ) : null}
    </section>
  );
}
