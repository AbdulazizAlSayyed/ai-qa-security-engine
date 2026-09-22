import { useState } from "react";

import StatusPill, { type Tone } from "@/components/StatusPill";
import { formatDuration, formatTimestamp } from "@/lib/assessment";
import type { Evidence } from "@/types/assessment";
import type { Retest } from "@/types/retests";

/** Status (did it execute?) and verdict (what did it conclude?) are kept apart:
 *  only a completed retest has a PASS / FAIL verdict. */
export function retestOutcome(retest: Retest): { label: string; tone: Tone; testId: string } {
  if (retest.status === "running") return { label: "Running", tone: "neutral", testId: "running" };
  if (retest.status === "failed") return { label: "Execution failed", tone: "warning", testId: "execution-failed" };
  if (retest.verdict === "PASS") return { label: "PASS", tone: "positive", testId: "pass" };
  if (retest.verdict === "FAIL") return { label: "FAIL", tone: "negative", testId: "fail" };
  return { label: "No verdict", tone: "neutral", testId: "no-verdict" };
}

export function RetestOutcome({ retest }: { retest: Retest }) {
  const outcome = retestOutcome(retest);
  return (
    <span data-testid={`retest-outcome-${outcome.testId}`}>
      <StatusPill tone={outcome.tone} pulse={retest.status === "running"}>
        {outcome.label}
      </StatusPill>
    </span>
  );
}

interface RetestsPanelProps {
  retests: Retest[] | null;
  loadError: string | null;
  evidenceById: Map<string, Evidence>;
  onShowEvidence: (evidenceId: string) => void;
  onShowIssue: (issueId: string) => void;
  onRefresh: () => void;
}

function RetestDetail({
  retest,
  evidenceById,
  onShowEvidence,
}: {
  retest: Retest;
  evidenceById: Map<string, Evidence>;
  onShowEvidence: (evidenceId: string) => void;
}) {
  return (
    <div className="flex flex-col gap-3 text-xs text-slate-300">
      <dl className="grid gap-2 sm:grid-cols-2">
        <div>
          <dt className="text-slate-500">Engine scope</dt>
          <dd className="font-mono break-all">
            {retest.plan.engine} ·{" "}
            {retest.plan.engine === "security" ? retest.plan.components.join(", ") : retest.plan.qa_checks.join(", ")}
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Passes when</dt>
          <dd>
            {retest.pass_condition === "finding_absent"
              ? "the issue's correlation key no longer appears"
              : "the same QA check reports passed"}
          </dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-slate-500">Match key</dt>
          <dd className="font-mono break-all text-slate-400">{retest.match_key}</dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-slate-500">Source runs</dt>
          <dd className="font-mono break-all text-slate-400">
            {retest.source_runs.length
              ? retest.source_runs.map((run) => `${run.engine}:${run.run_id} (${run.status ?? "?"})`).join(" · ")
              : "none"}
          </dd>
        </div>
      </dl>

      {retest.result_summary ? (
        <p>
          <span className="text-slate-500">Result: </span>
          {retest.result_summary.reason} ({retest.result_summary.matching_results} matching of{" "}
          {retest.result_summary.results_evaluated} results evaluated)
        </p>
      ) : null}

      {retest.error ? (
        <p role="alert" className="text-amber-200">
          Execution failed · <span className="font-mono">{retest.error.category}</span> — {retest.error.message}
          <span className="block text-slate-400">No verdict: the engine did not produce a usable result.</span>
        </p>
      ) : null}

      {retest.matched_evidence_ids.length ? (
        <div>
          <p className="text-slate-500">Original evidence observed again</p>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {retest.matched_evidence_ids.map((evidenceId, index) => {
              const record = evidenceById.get(evidenceId);
              const label = retest.matched_evidence_refs[index] ?? evidenceId.slice(0, 8);
              return (
                <button
                  key={evidenceId}
                  type="button"
                  onClick={() => onShowEvidence(evidenceId)}
                  aria-label={`Show evidence ${label}`}
                  title={record ? `${record.source} · ${record.title}` : evidenceId}
                  className="rounded-md border border-sky-500/30 bg-sky-500/5 px-2 py-0.5 font-mono text-[11px] text-sky-300 hover:bg-sky-500/15"
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>
      ) : null}

      {retest.observations.length ? (
        <div>
          <p className="text-slate-500">New results that decided the verdict (not stored as evidence)</p>
          <ul className="mt-1 flex flex-col gap-1">
            {retest.observations.map((item, index) => (
              <li key={`${item.source_finding_id ?? "obs"}-${index}`} className="font-mono text-[11px] break-all">
                {item.source} · {item.status} · {item.title} · {item.target_component}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function RetestRow({
  retest,
  expanded,
  onToggle,
  onShowIssue,
  evidenceById,
  onShowEvidence,
}: {
  retest: Retest;
  expanded: boolean;
  onToggle: () => void;
  onShowIssue: (issueId: string) => void;
  evidenceById: Map<string, Evidence>;
  onShowEvidence: (evidenceId: string) => void;
}) {
  return (
    <>
      <tr className="border-t border-slate-800 align-top text-slate-300" data-testid="retest-row">
        <td className="py-2 pr-3 font-mono text-slate-100">{retest.retest_id}</td>
        <td className="py-2 pr-3 font-mono">{retest.recommendation_id}</td>
        <td className="py-2 pr-3">
          <button
            type="button"
            onClick={() => onShowIssue(retest.issue_id)}
            className="font-mono text-sky-300 hover:underline"
            aria-label={`Open issue ${retest.issue_id}`}
          >
            {retest.issue_id.slice(0, 8)}…
          </button>
        </td>
        <td className="py-2 pr-3">
          {retest.type === "security_rescan" ? "Security rescan" : "QA re-check"} · {retest.scope}
        </td>
        <td className="max-w-[220px] py-2 pr-3 font-mono break-all text-slate-400">{retest.target_component}</td>
        <td className="py-2 pr-3">
          <RetestOutcome retest={retest} />
        </td>
        <td className="py-2 pr-3 whitespace-nowrap">{formatTimestamp(retest.started_at)}</td>
        <td className="py-2 pr-3 whitespace-nowrap">{formatDuration(retest.duration_ms)}</td>
        <td className="py-2">
          <button type="button" onClick={onToggle} aria-expanded={expanded} className="text-sky-300 hover:underline">
            {expanded ? "Hide" : "Details"}
          </button>
        </td>
      </tr>
      {expanded ? (
        <tr className="border-t border-slate-800/60">
          <td colSpan={9} className="py-3">
            <RetestDetail retest={retest} evidenceById={evidenceById} onShowEvidence={onShowEvidence} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

export default function RetestsPanel({
  retests,
  loadError,
  evidenceById,
  onShowEvidence,
  onShowIssue,
  onRefresh,
}: RetestsPanelProps) {
  const [open, setOpen] = useState<string | null>(null);
  const items = retests ?? [];

  return (
    <section
      id="retests"
      className="scroll-mt-6 rounded-xl border border-slate-800 bg-slate-900/60 p-5"
      aria-label="Retests"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-slate-100">Retests</h2>
          <p className="mt-1 max-w-2xl text-sm text-slate-400">
            Each retest re-runs only the checks in a recommendation&apos;s stored specification through the
            existing QA or security engine and compares the result deterministically. PASS means the issue
            was not observed again; FAIL means it was. Execution failed means the engine could not run, so
            there is no verdict. Nothing is fixed, and this assessment&apos;s evidence and priorities are not
            changed.
          </p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:border-slate-500"
        >
          Refresh retests
        </button>
      </div>

      {loadError ? (
        <p role="alert" className="mt-3 text-sm text-rose-300">
          Could not load retests: {loadError}
        </p>
      ) : null}

      {retests && items.length === 0 ? (
        <p className="mt-4 text-sm text-slate-500">
          No retests yet. Use Run Retest on a recommendation to execute its retest specification.
        </p>
      ) : null}

      {items.length > 0 ? (
        <div className="relative mt-4 overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-xs">
            <thead className="text-[11px] tracking-wide text-slate-500 uppercase">
              <tr>
                <th className="py-2 pr-3 font-medium">Retest</th>
                <th className="py-2 pr-3 font-medium">Recommendation</th>
                <th className="py-2 pr-3 font-medium">Issue</th>
                <th className="py-2 pr-3 font-medium">Type</th>
                <th className="py-2 pr-3 font-medium">Component</th>
                <th className="py-2 pr-3 font-medium">Outcome</th>
                <th className="py-2 pr-3 font-medium">Started</th>
                <th className="py-2 pr-3 font-medium">Duration</th>
                <th className="py-2 font-medium">
                  <span className="sr-only">Details</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((retest) => {
                const expanded = open === retest.retest_id;
                return (
                  <RetestRow
                    key={retest.retest_id}
                    retest={retest}
                    expanded={expanded}
                    onToggle={() => setOpen(expanded ? null : retest.retest_id)}
                    onShowIssue={onShowIssue}
                    evidenceById={evidenceById}
                    onShowEvidence={onShowEvidence}
                  />
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
