import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import StatusPill, { type Tone } from "@/components/StatusPill";
import SeverityBadge from "@/components/security/SeverityBadge";
import { formatDuration, formatTimestamp } from "@/lib/assessment";
import { getAIAnalysis, startAIAnalysis } from "@/services/aiAnalysis";
import type { AIAnalysis, AIAnalysisView, AIFinding } from "@/types/aiAnalysis";
import type { Assessment, Evidence } from "@/types/assessment";

interface AIAnalysisPanelProps {
  assessment: Assessment;
  /** evidence_id -> record, to label and resolve references. */
  evidenceById: Map<string, Evidence>;
  onShowEvidence: (evidenceId: string) => void;
  /** Called after an analysis attempt so the page can re-read the assessment. */
  onAnalysed: () => void;
}

type PanelStatus = "not_analyzed" | "analyzing" | "completed" | "failed";

const STATUS_LABEL: Record<PanelStatus, string> = {
  not_analyzed: "Not analyzed",
  analyzing: "Analyzing",
  completed: "Analysis completed",
  failed: "Analysis failed",
};

const STATUS_TONE: Record<PanelStatus, Tone> = {
  not_analyzed: "neutral",
  analyzing: "neutral",
  completed: "positive",
  failed: "negative",
};

const CONFIDENCE_CLASS: Record<AIFinding["confidence"], string> = {
  high: "text-emerald-300",
  medium: "text-amber-300",
  low: "text-slate-400",
};

function panelStatus(view: AIAnalysisView | null, analyzing: boolean): PanelStatus {
  if (analyzing) return "analyzing";
  if (!view || view.status === "not_analyzed") return "not_analyzed";
  if (view.status === "created" || view.status === "running") return "analyzing";
  return view.status;
}

function Block({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <p className="text-[11px] tracking-wide text-slate-500 uppercase">{label}</p>
      <div className="mt-0.5 text-sm whitespace-pre-line text-slate-200">{children}</div>
    </div>
  );
}

function FindingCard({
  finding,
  evidenceById,
  onShowEvidence,
}: {
  finding: AIFinding;
  evidenceById: Map<string, Evidence>;
  onShowEvidence: (evidenceId: string) => void;
}) {
  return (
    <li className="rounded-xl border border-slate-800 bg-slate-950/50 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`rounded-md px-2 py-0.5 text-[11px] font-medium uppercase ${
            finding.type === "security"
              ? "bg-rose-500/10 text-rose-300"
              : "bg-sky-500/10 text-sky-300"
          }`}
        >
          {finding.type === "security" ? "Security" : "QA"}
        </span>
        <span className="font-mono text-[11px] text-slate-500">{finding.finding_id}</span>
        {finding.status === "insufficient_evidence" ? (
          <span className="rounded-md bg-amber-500/10 px-2 py-0.5 text-[11px] text-amber-300">
            Insufficient evidence
          </span>
        ) : null}
      </div>

      <h4 className="mt-2 text-sm font-semibold text-slate-100">{finding.title}</h4>

      <dl className="mt-3 grid gap-3 sm:grid-cols-3">
        <div>
          <dt className="text-[11px] tracking-wide text-slate-500 uppercase">Confidence</dt>
          <dd className={`mt-0.5 text-sm capitalize ${CONFIDENCE_CLASS[finding.confidence]}`}>
            {finding.confidence}
            <span className="ml-1 text-[11px] normal-case text-slate-500">(AI interpretation)</span>
          </dd>
        </div>
        <div>
          <dt className="text-[11px] tracking-wide text-slate-500 uppercase">Tool severity</dt>
          <dd className="mt-0.5">
            {finding.tool_severity ? (
              <SeverityBadge severity={finding.tool_severity} />
            ) : (
              <span className="text-sm text-slate-500">— (none reported by a tool)</span>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] tracking-wide text-slate-500 uppercase">
            Affected components
          </dt>
          <dd className="mt-0.5 font-mono text-[11px] break-all text-slate-300">
            {finding.affected_components.join(" · ") || "—"}
          </dd>
        </div>
      </dl>

      <div className="mt-3 flex flex-col gap-3">
        <Block label="Description">{finding.description}</Block>
        <Block label="Impact">{finding.impact}</Block>
        <Block label="Uncertainty">{finding.uncertainty}</Block>
      </div>

      <div className="mt-3">
        <p className="text-[11px] tracking-wide text-slate-500 uppercase">
          Evidence ({finding.evidence_ids.length})
        </p>
        <div className="mt-1 flex flex-wrap gap-1.5">
          {finding.evidence_ids.map((evidenceId, index) => {
            const record = evidenceById.get(evidenceId);
            const ref = finding.evidence_refs[index] ?? evidenceId.slice(0, 8);
            return (
              <button
                key={evidenceId}
                type="button"
                onClick={() => onShowEvidence(evidenceId)}
                aria-label={`Show evidence ${ref}${record ? `: ${record.title}` : ""}`}
                title={
                  record
                    ? `${record.source} · ${record.title} · ${record.target_component}`
                    : evidenceId
                }
                className="rounded-md border border-sky-500/30 bg-sky-500/5 px-2 py-0.5 font-mono text-[11px] text-sky-300 transition-colors hover:bg-sky-500/15"
              >
                {ref}
              </button>
            );
          })}
        </div>
      </div>
    </li>
  );
}

function AnalysisBody({
  analysis,
  evidenceById,
  onShowEvidence,
}: {
  analysis: AIAnalysis;
  evidenceById: Map<string, Evidence>;
  onShowEvidence: (evidenceId: string) => void;
}) {
  const result = analysis.result;
  if (!result) return null;
  const { context } = analysis;

  return (
    <div className="flex flex-col gap-4">
      <p className="font-mono text-[11px] text-slate-500">
        {analysis.provider} · {analysis.model} · contract v{analysis.analysis_version} ·{" "}
        {context.supplied_evidence} of {context.total_evidence} evidence records supplied
        {context.omitted.length ? ` · ${context.omitted.length} omitted for size` : ""}
        {context.redactions ? ` · ${context.redactions} secret-like values redacted` : ""} ·{" "}
        {formatDuration(analysis.duration_ms)} · {formatTimestamp(analysis.completed_at)}
      </p>

      <Block label="Overall assessment">{result.overall_assessment}</Block>

      <div>
        <h3 className="text-sm font-semibold text-slate-200">
          AI findings ({result.findings.length})
        </h3>
        {result.findings.length === 0 ? (
          <p className="mt-2 text-sm text-slate-500">The analysis reported no findings.</p>
        ) : (
          <ul className="mt-2 flex flex-col gap-3">
            {result.findings.map((finding) => (
              <FindingCard
                key={finding.finding_id}
                finding={finding}
                evidenceById={evidenceById}
                onShowEvidence={onShowEvidence}
              />
            ))}
          </ul>
        )}
      </div>

      {result.evidence_gaps.length ? (
        <div>
          <h3 className="text-sm font-semibold text-slate-200">Evidence gaps</h3>
          <ul className="mt-1 list-disc pl-5 text-sm text-slate-300">
            {result.evidence_gaps.map((gap) => (
              <li key={gap}>{gap}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {result.limitations.length ? (
        <div>
          <h3 className="text-sm font-semibold text-slate-200">Limitations</h3>
          <ul className="mt-1 list-disc pl-5 text-sm text-slate-300">
            {result.limitations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export default function AIAnalysisPanel({
  assessment,
  evidenceById,
  onShowEvidence,
  onAnalysed,
}: AIAnalysisPanelProps) {
  const [view, setView] = useState<AIAnalysisView | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const inFlight = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;
    try {
      const loaded = await getAIAnalysis(assessment.id, controller.signal);
      if (controller.signal.aborted) return;
      setView(loaded);
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

  const handleAnalyze = useCallback(async () => {
    setAnalyzing(true);
    setRunError(null);
    try {
      await startAIAnalysis(assessment.id);
    } catch (caught) {
      // A failed analysis is recorded server-side; the re-read below shows it.
      setRunError(
        caught instanceof Error ? caught.message : "The analysis could not be started.",
      );
    } finally {
      setAnalyzing(false);
      await load();
      onAnalysed();
    }
  }, [assessment.id, load, onAnalysed]);

  const status = panelStatus(view, analyzing);
  const latest = view?.latest ?? null;
  const completed = view?.latest_completed ?? null;
  const eligible = assessment.status === "completed" && assessment.evidence_count > 0;

  return (
    <section
      className="rounded-xl border border-slate-800 bg-slate-900/60 p-5"
      aria-label="AI Analysis"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold text-slate-100">AI Analysis</h2>
            <StatusPill tone={STATUS_TONE[status]} pulse={status === "analyzing"}>
              {STATUS_LABEL[status]}
            </StatusPill>
          </div>
          <p className="mt-1 max-w-2xl text-sm text-slate-400">
            Reads only this assessment&apos;s normalized evidence. The AI runs no tests, every
            finding must cite evidence below, and tool severity is never changed.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void handleAnalyze()}
          disabled={!eligible || status === "analyzing"}
          title={
            eligible ? undefined : "Only a completed assessment with evidence can be analysed."
          }
          className="rounded-lg bg-sky-500 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {status === "analyzing"
            ? "Analyzing..."
            : completed
              ? "Analyze Again"
              : "Analyze Assessment"}
        </button>
      </div>

      {status === "analyzing" ? (
        <p className="mt-4 flex items-center gap-2 text-sm text-sky-300">
          <span className="size-1.5 animate-pulse rounded-full bg-sky-400" />
          Sending {assessment.evidence_count} evidence records to the configured AI provider and
          validating the answer…
        </p>
      ) : null}

      {loadError ? (
        <p role="alert" className="mt-4 text-sm text-rose-300">
          Could not load the analysis: {loadError}
        </p>
      ) : null}

      {status === "failed" && latest?.error ? (
        <div
          role="alert"
          className="mt-4 rounded-lg border border-rose-500/30 bg-rose-500/5 px-4 py-3"
        >
          <p className="text-sm font-medium text-rose-200">
            Analysis failed · <span className="font-mono">{latest.error.category}</span>
          </p>
          <p className="mt-1 text-sm text-rose-200/80">{latest.error.message}</p>
          <p className="mt-1 font-mono text-[11px] text-rose-200/50">
            {latest.analysis_id} · {latest.provider} · {latest.model || "no model configured"} ·{" "}
            {formatTimestamp(latest.completed_at ?? latest.created_at)}
          </p>
          <p className="mt-2 text-xs text-slate-400">
            The technical assessment is unaffected. Nothing from a failed analysis is shown as a
            result.
          </p>
        </div>
      ) : null}

      {runError && status !== "failed" ? (
        <p role="alert" className="mt-4 text-sm text-rose-300">
          {runError}
        </p>
      ) : null}

      {completed ? (
        <div className="mt-5">
          {latest && latest.analysis_id !== completed.analysis_id ? (
            <p className="mb-3 text-xs text-slate-500">
              Showing the last completed analysis ({completed.analysis_id.slice(0, 8)}…).
            </p>
          ) : null}
          <AnalysisBody
            analysis={completed}
            evidenceById={evidenceById}
            onShowEvidence={onShowEvidence}
          />
        </div>
      ) : null}

      {status === "not_analyzed" && !loadError ? (
        <p className="mt-4 text-sm text-slate-500">
          No analysis yet. Analysis runs only when you ask for it.
        </p>
      ) : null}
    </section>
  );
}
