import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import StatusPill, { type Tone } from "@/components/StatusPill";
import PriorityBadge from "@/components/issues/PriorityBadge";
import { RetestOutcome } from "@/components/retests/RetestsPanel";
import { formatDuration, formatTimestamp } from "@/lib/assessment";
import { generateRecommendations, getRecommendations } from "@/services/recommendations";
import type { Assessment, Evidence } from "@/types/assessment";
import type { Priority } from "@/types/issues";
import type {
  Recommendation,
  RecommendationType,
  RecommendationsView,
  RetestSpecification,
} from "@/types/recommendations";
import type { Retest } from "@/types/retests";

interface RecommendationsPanelProps {
  assessment: Assessment;
  evidenceById: Map<string, Evidence>;
  onShowEvidence: (evidenceId: string) => void;
  /** Open the issue in the Prioritized Issues panel. */
  onShowIssue: (issueId: string) => void;
  onGenerated: () => void;
  /** Retest history of the assessment, newest first (null while loading). */
  retests: Retest[] | null;
  /** Recommendation document id whose retest is executing right now. */
  runningRetestFor: string | null;
  retestErrors: Record<string, string>;
  onRunRetest: (item: Recommendation) => void;
}

const TYPE_LABEL: Record<RecommendationType, string> = {
  configuration_change: "Configuration change",
  code_change: "Code change",
  dependency_update: "Dependency update",
  investigation: "Investigation",
  qa_test_improvement: "QA test improvement",
};

const STATUS_LABEL: Record<RecommendationsView["status"], string> = {
  not_generated: "Not generated",
  running: "Generating",
  completed: "Generated",
  failed: "Generation failed",
};

const STATUS_TONE: Record<RecommendationsView["status"], Tone> = {
  not_generated: "neutral",
  running: "neutral",
  completed: "positive",
  failed: "negative",
};

const PRIORITIES = new Set(["P1", "P2", "P3", "P4"]);

function AdvisoryBadge() {
  return (
    <span
      className="rounded-md bg-violet-500/15 px-2 py-0.5 text-[11px] font-medium text-violet-200 ring-1 ring-violet-400/30 ring-inset"
      title="Advisory only. The platform never applies, executes or verifies a recommendation."
    >
      Advisory
    </span>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <p className="text-[11px] tracking-wide text-slate-500 uppercase">{label}</p>
      <div className="mt-0.5 text-sm whitespace-pre-line text-slate-200">{children}</div>
    </div>
  );
}

function EvidenceChip({
  evidenceId,
  label,
  evidenceById,
  onShowEvidence,
}: {
  evidenceId: string;
  label: string;
  evidenceById: Map<string, Evidence>;
  onShowEvidence: (evidenceId: string) => void;
}) {
  const record = evidenceById.get(evidenceId);
  return (
    <button
      type="button"
      onClick={() => onShowEvidence(evidenceId)}
      aria-label={`Show evidence ${label}${record ? `: ${record.title}` : ""}`}
      title={record ? `${record.source} · ${record.title} · ${record.target_component}` : evidenceId}
      className="rounded-md border border-sky-500/30 bg-sky-500/5 px-2 py-0.5 font-mono text-[11px] text-sky-300 transition-colors hover:bg-sky-500/15"
    >
      {label}
    </button>
  );
}

function IssueLink({ issueId, onShowIssue }: { issueId: string; onShowIssue: (id: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onShowIssue(issueId)}
      aria-label={`Open issue ${issueId}`}
      className="font-mono text-xs text-sky-300 underline-offset-2 hover:underline"
    >
      {issueId}
    </button>
  );
}

function RetestBlock({
  spec,
  evidenceById,
  onShowEvidence,
}: {
  spec: RetestSpecification;
  evidenceById: Map<string, Evidence>;
  onShowEvidence: (evidenceId: string) => void;
}) {
  return (
    <div className="mt-3 rounded-lg border border-dashed border-slate-700 bg-slate-950/40 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-semibold text-slate-300">Retest specification</p>
        <span className="text-[11px] text-slate-500">Runs only when you click Run Retest</span>
      </div>
      <dl className="mt-2 grid gap-2 text-xs sm:grid-cols-2">
        <div>
          <dt className="text-slate-500">Retest</dt>
          <dd className="font-mono text-slate-200">
            {spec.retest_type === "security_rescan" ? "Security rescan" : "QA re-check"} · {spec.scope}
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Target component</dt>
          <dd className="font-mono break-all text-slate-200">{spec.target_component}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Passes when</dt>
          <dd className="text-slate-200">
            {spec.pass_condition === "finding_absent"
              ? "the issue's correlation key no longer appears"
              : "the same QA check reports passed"}
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Match key</dt>
          <dd className="font-mono break-all text-slate-400">{spec.match_key}</dd>
        </div>
      </dl>
      <div className="mt-2">
        <p className="text-[11px] tracking-wide text-slate-500 uppercase">Checks to re-run</p>
        <ul className="mt-1 flex flex-col gap-1">
          {spec.checks.map((check) => (
            <li key={check.evidence_id} className="flex flex-wrap items-center gap-2 text-xs text-slate-300">
              <EvidenceChip
                evidenceId={check.evidence_id}
                label={check.evidence_ref}
                evidenceById={evidenceById}
                onShowEvidence={onShowEvidence}
              />
              <span className="font-mono text-slate-400">
                {check.source}
                {check.rule_id ? ` · rule ${check.rule_id}` : ""}
              </span>
              <span>{check.title}</span>
              <span className="text-slate-500">(was {check.baseline_status})</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-3">
        <Field label="Expected">{spec.expected_result}</Field>
        <Field label="PASS">{spec.pass_criteria}</Field>
        <Field label="FAIL">{spec.fail_criteria}</Field>
      </div>
      {spec.preconditions.length ? (
        <div className="mt-2">
          <p className="text-[11px] tracking-wide text-slate-500 uppercase">Preconditions</p>
          <ul className="mt-0.5 list-disc pl-5 text-xs text-slate-300">
            {spec.preconditions.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function RecommendationCard({
  item,
  evidenceById,
  onShowEvidence,
  onShowIssue,
  history,
  running,
  retestBlocker,
  retestError,
  onRunRetest,
}: {
  item: Recommendation;
  evidenceById: Map<string, Evidence>;
  onShowEvidence: (evidenceId: string) => void;
  onShowIssue: (issueId: string) => void;
  history: Retest[];
  running: boolean;
  retestBlocker: string | null;
  retestError: string | null;
  onRunRetest: (item: Recommendation) => void;
}) {
  return (
    <li
      className="rounded-xl border border-violet-500/20 bg-slate-950/50 p-4"
      data-testid="recommendation-card"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-violet-200">{item.recommendation_id}</span>
        <AdvisoryBadge />
        <span className="rounded-md bg-slate-800 px-2 py-0.5 text-[11px] text-slate-300">
          {TYPE_LABEL[item.type]}
        </span>
        <span className="text-[11px] text-slate-500">
          {item.confidence} confidence (AI advice, not a severity)
        </span>
      </div>

      <h4 className="mt-2 text-sm font-semibold text-slate-100">{item.title}</h4>

      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-400">
        <span>For issue</span>
        <IssueLink issueId={item.issue_id} onShowIssue={onShowIssue} />
        {PRIORITIES.has(item.issue_priority) ? (
          <span className="flex items-center gap-1">
            <span className="text-slate-500">issue priority</span>
            <PriorityBadge priority={item.issue_priority as Priority} />
          </span>
        ) : null}
        {item.related_issue_ids.length ? (
          <span className="flex items-center gap-1">
            <span className="text-slate-500">also</span>
            {item.related_issue_ids.map((id) => (
              <IssueLink key={id} issueId={id} onShowIssue={onShowIssue} />
            ))}
          </span>
        ) : null}
      </div>

      <p className="mt-2 font-mono text-[11px] break-all text-slate-400">
        {item.affected_components.join(" · ")}
      </p>

      <div className="mt-3 flex flex-col gap-3">
        <Field label="Recommendation">{item.description}</Field>
        <Field label="Why">{item.rationale}</Field>
      </div>

      <div className="mt-3">
        <p className="text-[11px] tracking-wide text-slate-500 uppercase">
          Supporting evidence ({item.evidence_ids.length})
        </p>
        <div className="mt-1 flex flex-wrap gap-1.5">
          {item.evidence_ids.map((evidenceId, index) => (
            <EvidenceChip
              key={evidenceId}
              evidenceId={evidenceId}
              label={item.evidence_refs[index] ?? evidenceId.slice(0, 8)}
              evidenceById={evidenceById}
              onShowEvidence={onShowEvidence}
            />
          ))}
        </div>
      </div>

      <RetestBlock spec={item.retest} evidenceById={evidenceById} onShowEvidence={onShowEvidence} />
      <RetestControls
        item={item}
        history={history}
        running={running}
        blocker={retestBlocker}
        error={retestError}
        onRunRetest={onRunRetest}
      />
    </li>
  );
}

function RetestControls({
  item,
  history,
  running,
  blocker,
  error,
  onRunRetest,
}: {
  item: Recommendation;
  history: Retest[];
  running: boolean;
  blocker: string | null;
  error: string | null;
  onRunRetest: (item: Recommendation) => void;
}) {
  const latest = history[0] ?? null;
  return (
    <div className="mt-3 rounded-lg border border-slate-800 bg-slate-950/40 p-3" data-testid="recommendation-retest">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
          <span className="font-semibold text-slate-300">Latest retest</span>
          {running ? (
            <span data-testid="retest-outcome-running">
              <StatusPill tone="neutral" pulse>
                Running
              </StatusPill>
            </span>
          ) : latest ? (
            <>
              <span className="font-mono text-slate-200">{latest.retest_id}</span>
              <RetestOutcome retest={latest} />
              <span>{formatTimestamp(latest.completed_at ?? latest.started_at)}</span>
            </>
          ) : (
            <span>Not retested yet</span>
          )}
        </div>
        <button
          type="button"
          onClick={() => onRunRetest(item)}
          disabled={running || Boolean(blocker)}
          title={blocker ?? "Re-run only the checks in this retest specification"}
          aria-label={`Run retest for ${item.recommendation_id}`}
          className="rounded-lg bg-sky-500 px-3 py-1.5 text-xs font-medium text-slate-950 transition-colors hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {running ? "Running retest..." : "Run Retest"}
        </button>
      </div>
      {error ? (
        <p role="alert" className="mt-2 text-xs text-amber-200">
          {error}
        </p>
      ) : null}
      {history.length > 1 ? (
        <p className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
          <span>History ({history.length}):</span>
          {history.map((retest) => (
            <span key={retest.retest_id} className="font-mono">
              {retest.retest_id}{" "}
              {retest.status === "completed" ? retest.verdict : retest.status === "failed" ? "execution failed" : "running"}
            </span>
          ))}
        </p>
      ) : null}
    </div>
  );
}

function missingPrerequisite(assessment: Assessment): string | null {
  if (assessment.status !== "completed") return "The assessment must be completed and not being analysed.";
  if (assessment.ai_analysis_status === "not_analyzed") return "Run AI Analysis first.";
  if (assessment.correlation?.status !== "completed") return "Run Correlate & Prioritize first.";
  if (assessment.correlation.issue_count === 0) return "Correlation found no issues to recommend on.";
  return null;
}

export default function RecommendationsPanel({
  assessment,
  evidenceById,
  onShowEvidence,
  onShowIssue,
  onGenerated,
  retests,
  runningRetestFor,
  retestErrors,
  onRunRetest,
}: RecommendationsPanelProps) {
  const [view, setView] = useState<RecommendationsView | null>(null);
  const [selectedSet, setSelectedSet] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const inFlight = useRef<AbortController | null>(null);

  const load = useCallback(
    async (setId: string | null) => {
      inFlight.current?.abort();
      const controller = new AbortController();
      inFlight.current = controller;
      try {
        const loaded = await getRecommendations(assessment.id, setId, controller.signal);
        if (controller.signal.aborted) return;
        setView(loaded);
        setLoadError(null);
      } catch (caught) {
        if (controller.signal.aborted) return;
        setLoadError(caught instanceof Error ? caught.message : "Unexpected error");
      }
    },
    [assessment.id],
  );

  useEffect(() => {
    void load(selectedSet);
    return () => inFlight.current?.abort();
  }, [load, selectedSet]);

  const handleGenerate = useCallback(async () => {
    setGenerating(true);
    setRunError(null);
    try {
      const generated = await generateRecommendations(assessment.id);
      setSelectedSet(null);
      setView(generated);
    } catch (caught) {
      // A failed generation is recorded server-side; the re-read shows it.
      setRunError(caught instanceof Error ? caught.message : "Recommendations could not be generated.");
      await load(null);
    } finally {
      setGenerating(false);
      onGenerated();
    }
  }, [assessment.id, load, onGenerated]);

  const status = generating ? "running" : (view?.status ?? "not_generated");
  const blocker = missingPrerequisite(assessment);
  const generation = view?.generation ?? null;
  const items = view?.recommendations ?? [];
  const hasSet = items.length > 0 || Boolean(view?.ai_analysis_id);

  return (
    <section
      id="recommendations"
      className="scroll-mt-6 rounded-xl border border-slate-800 bg-slate-900/60 p-5"
      aria-label="Recommendations"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold text-slate-100">Recommendations</h2>
            <AdvisoryBadge />
            <StatusPill tone={STATUS_TONE[status]} pulse={status === "running"}>
              {STATUS_LABEL[status]}
            </StatusPill>
          </div>
          <p className="mt-1 max-w-2xl text-sm text-slate-400">
            Advice for the prioritized issues, written by the AI from this assessment&apos;s stored
            evidence and AI analysis. A recommendation is not a confirmed vulnerability, not a
            severity and not a priority. Nothing is applied or executed; a retest runs only when you
            click Run Retest, and it re-runs the specified checks without changing anything.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void handleGenerate()}
          disabled={Boolean(blocker) || generating}
          title={blocker ?? undefined}
          className="rounded-lg bg-violet-500 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-violet-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {generating
            ? "Generating..."
            : generation?.status === "completed" || hasSet
              ? "Regenerate Recommendations"
              : "Generate Recommendations"}
        </button>
      </div>

      {blocker && !generating ? <p className="mt-3 text-xs text-slate-500">{blocker}</p> : null}

      {generation && generation.status !== "running" ? (
        <p className="mt-3 font-mono text-[11px] text-slate-500">
          Last generation: {generation.provider} · {generation.model || "no model configured"} · contract v
          {generation.recommendation_version ?? "?"} · {generation.issues_supplied} issues
          {generation.issues_omitted.length ? ` (${generation.issues_omitted.length} omitted for size)` : ""} ·{" "}
          {generation.evidence_supplied} evidence records · {formatDuration(generation.duration_ms)} ·{" "}
          {formatTimestamp(generation.completed_at)}
        </p>
      ) : null}

      {generation?.status === "failed" && generation.error ? (
        <div role="alert" className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/5 px-4 py-3">
          <p className="text-sm font-medium text-rose-200">
            Generation failed · <span className="font-mono">{generation.error.category}</span>
          </p>
          <p className="mt-1 text-sm text-rose-200/80">{generation.error.message}</p>
          <p className="mt-2 text-xs text-slate-400">
            Nothing from a failed generation is shown. Earlier recommendations, if any, are unchanged.
          </p>
        </div>
      ) : null}
      {runError && generation?.status !== "failed" ? (
        <p role="alert" className="mt-3 text-sm text-rose-300">
          {runError}
        </p>
      ) : null}
      {loadError ? (
        <p role="alert" className="mt-3 text-sm text-rose-300">
          Could not load recommendations: {loadError}
        </p>
      ) : null}

      {view && hasSet && !view.is_current ? (
        <p className="mt-3 text-xs text-amber-300">
          These recommendations come from AI analysis {view.ai_analysis_id?.slice(0, 8)}…, which is not the
          current analysis or correlation. Re-run Correlate &amp; Prioritize if needed, then regenerate.
        </p>
      ) : null}

      {view && view.sets.length > 1 ? (
        <div className="mt-3 flex items-center gap-2 text-xs text-slate-400">
          <label htmlFor="recommendation-set">Recommendation set</label>
          <select
            id="recommendation-set"
            value={selectedSet ?? view.ai_analysis_id ?? ""}
            onChange={(event) => setSelectedSet(event.target.value || null)}
            className="rounded-md border border-slate-700 bg-slate-950/60 px-2 py-1 font-mono text-xs text-slate-200"
          >
            {view.sets.map((set) => (
              <option key={set.ai_analysis_id} value={set.ai_analysis_id}>
                analysis {set.ai_analysis_id.slice(0, 8)}… · {set.count} · {formatTimestamp(set.updated_at)}
                {set.ai_analysis_id === view.current_ai_analysis_id ? " (current)" : ""}
              </option>
            ))}
          </select>
        </div>
      ) : null}

      {items.length > 0 ? (
        <ul className="mt-4 flex flex-col gap-3">
          {items.map((item) => (
            <RecommendationCard
              key={item.recommendation_id}
              item={item}
              evidenceById={evidenceById}
              onShowEvidence={onShowEvidence}
              onShowIssue={onShowIssue}
              history={(retests ?? []).filter((retest) => retest.recommendation_ref === item.id)}
              running={runningRetestFor === item.id}
              retestBlocker={
                assessment.status !== "completed" ? "The assessment must be completed to run a retest." : null
              }
              retestError={retestErrors[item.id] ?? null}
              onRunRetest={onRunRetest}
            />
          ))}
        </ul>
      ) : null}

      {view && !hasSet && generation?.status !== "failed" ? (
        <p className="mt-4 text-sm text-slate-500">
          {generation?.status === "completed"
            ? "The last generation produced no recommendations."
            : "No recommendations yet. They are generated only when you ask for them."}
        </p>
      ) : null}
    </section>
  );
}
