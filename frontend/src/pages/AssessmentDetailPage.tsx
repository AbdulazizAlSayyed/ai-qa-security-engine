import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";

import AIAnalysisPanel from "@/components/assessments/AIAnalysisPanel";
import AssessmentDetails from "@/components/assessments/AssessmentDetails";
import EvidenceTable from "@/components/assessments/EvidenceTable";
import IssuesPanel from "@/components/issues/IssuesPanel";
import RecommendationsPanel from "@/components/recommendations/RecommendationsPanel";
import ReportsPanel from "@/components/reports/ReportsPanel";
import RetestsPanel from "@/components/retests/RetestsPanel";
import { ACTIVE_STATES } from "@/lib/assessment";
import { getAssessment, getAssessmentEvidence } from "@/services/assessments";
import { listRetests, runRetest } from "@/services/retests";
import type { Assessment, Evidence } from "@/types/assessment";
import type { Recommendation } from "@/types/recommendations";
import type { Retest } from "@/types/retests";

const POLL_MS = 1500;

export default function AssessmentDetailPage() {
  const { id = "" } = useParams<{ id: string }>();

  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [evidence, setEvidence] = useState<Evidence[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [focus, setFocus] = useState<{ id: string | null; nonce: number }>({ id: null, nonce: 0 });
  const inFlight = useRef<AbortController | null>(null);

  const evidenceById = useMemo(
    () => new Map((evidence ?? []).map((item) => [item.evidence_id, item])),
    [evidence],
  );

  /** An AI finding's or an issue's evidence reference was clicked: show that record. */
  const showEvidence = useCallback((evidenceId: string) => {
    setFocus((current) => ({ id: evidenceId, nonce: current.nonce + 1 }));
  }, []);

  /** A recommendation's issue reference was clicked: open that issue. */
  const [issueFocus, setIssueFocus] = useState<{ id: string | null; nonce: number }>({
    id: null,
    nonce: 0,
  });
  const showIssue = useCallback((issueId: string) => {
    setIssueFocus((current) => ({ id: issueId, nonce: current.nonce + 1 }));
  }, []);

  const load = useCallback(async () => {
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;
    try {
      const loaded = await getAssessment(id, controller.signal);
      if (controller.signal.aborted) return;
      setAssessment(loaded);
      setError(null);
      // Evidence is written once, when normalization finishes.
      if (!ACTIVE_STATES.has(loaded.status)) {
        const items = await getAssessmentEvidence(id, 2000, controller.signal);
        if (!controller.signal.aborted) setEvidence(items);
      }
    } catch (caught) {
      if (controller.signal.aborted) return;
      setError(caught instanceof Error ? caught.message : "Unexpected error");
    }
  }, [id]);

  useEffect(() => {
    setAssessment(null);
    setEvidence(null);
    void load();
    return () => inFlight.current?.abort();
  }, [load]);

  // Retest history (Phase 9). Shared by the recommendation cards and the Retests section.
  const [retests, setRetests] = useState<Retest[] | null>(null);
  const [retestLoadError, setRetestLoadError] = useState<string | null>(null);
  const [runningRetestFor, setRunningRetestFor] = useState<string | null>(null);
  const [retestErrors, setRetestErrors] = useState<Record<string, string>>({});
  const retestsInFlight = useRef<AbortController | null>(null);

  const loadRetests = useCallback(async () => {
    retestsInFlight.current?.abort();
    const controller = new AbortController();
    retestsInFlight.current = controller;
    try {
      const items = await listRetests(id, controller.signal);
      if (controller.signal.aborted) return;
      setRetests(items);
      setRetestLoadError(null);
    } catch (caught) {
      if (controller.signal.aborted) return;
      setRetestLoadError(caught instanceof Error ? caught.message : "Unexpected error");
    }
  }, [id]);

  useEffect(() => {
    setRetests(null);
    setRetestErrors({});
    void loadRetests();
    return () => retestsInFlight.current?.abort();
  }, [loadRetests]);

  /** Execute the stored retest specification. The server decides the scope;
   *  a failed execution is recorded and shows up in the re-read history. */
  const handleRunRetest = useCallback(
    async (item: Recommendation) => {
      setRunningRetestFor(item.id);
      setRetestErrors(({ [item.id]: _previous, ...rest }) => rest);
      try {
        await runRetest(id, item.recommendation_id, item.ai_analysis_id);
      } catch (caught) {
        const message = caught instanceof Error ? caught.message : "The retest could not be run.";
        setRetestErrors((current) => ({ ...current, [item.id]: message }));
      } finally {
        setRunningRetestFor(null);
        await loadRetests();
      }
    },
    [id, loadRetests],
  );

  // Drill-down links (e.g. from the dashboard) may target a section by hash,
  // such as #prioritized-issues. Scroll once that section has rendered.
  const { hash } = useLocation();
  const evidenceLoaded = evidence !== null;
  useEffect(() => {
    if (!hash || !evidenceLoaded) return;
    const timer = window.setTimeout(() => {
      document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 50);
    return () => window.clearTimeout(timer);
  }, [hash, evidenceLoaded]);

  // While the pipeline is still moving, keep re-reading its real state.
  const active = assessment !== null && ACTIVE_STATES.has(assessment.status);
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [active, load]);

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <Link to="/assessments" className="text-xs text-sky-300 hover:text-sky-200">
            &larr; All assessments
          </Link>
          <h1 className="mt-1 text-2xl font-semibold text-slate-100">
            {assessment ? assessment.target_name : "Assessment"}
          </h1>
          <p className="mt-1 font-mono text-xs break-all text-slate-500">{id}</p>
        </div>
        <button
          type="button"
          onClick={() => {
            void load();
            void loadRetests();
          }}
          className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:bg-slate-800/60"
        >
          Refresh
        </button>
      </header>

      {error ? (
        <div role="alert" className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-5">
          <p className="font-medium text-rose-200">Unable to load this assessment</p>
          <p className="mt-1 font-mono text-xs text-rose-200/80">{error}</p>
        </div>
      ) : null}

      {assessment === null && !error ? (
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-10 text-center">
          <p className="text-sm text-slate-400">Loading assessment...</p>
        </div>
      ) : null}

      {assessment ? <AssessmentDetails assessment={assessment} /> : null}

      {assessment && active ? (
        <p className="flex items-center gap-2 text-sm text-sky-300">
          <span className="size-1.5 animate-pulse rounded-full bg-sky-400" />
          Evidence appears once normalization has finished.
        </p>
      ) : null}

      {assessment && !active && evidence ? (
        <AIAnalysisPanel
          assessment={assessment}
          evidenceById={evidenceById}
          onShowEvidence={showEvidence}
          onAnalysed={() => void load()}
        />
      ) : null}

      {assessment && !active && evidence ? (
        <IssuesPanel
          assessment={assessment}
          evidenceById={evidenceById}
          onShowEvidence={showEvidence}
          onProcessed={() => void load()}
          focusIssueId={issueFocus.id}
          focusNonce={issueFocus.nonce}
        />
      ) : null}

      {assessment && !active && evidence ? (
        <RecommendationsPanel
          assessment={assessment}
          evidenceById={evidenceById}
          onShowEvidence={showEvidence}
          onShowIssue={showIssue}
          onGenerated={() => void load()}
          retests={retests}
          runningRetestFor={runningRetestFor}
          retestErrors={retestErrors}
          onRunRetest={(item) => void handleRunRetest(item)}
        />
      ) : null}

      {assessment && !active && evidence ? (
        <RetestsPanel
          retests={retests}
          loadError={retestLoadError}
          evidenceById={evidenceById}
          onShowEvidence={showEvidence}
          onShowIssue={showIssue}
          onRefresh={() => void loadRetests()}
        />
      ) : null}

      {assessment && !active && evidence ? <ReportsPanel assessment={assessment} /> : null}

      {evidence ? (
        <EvidenceTable evidence={evidence} focusEvidenceId={focus.id} focusNonce={focus.nonce} />
      ) : null}
    </div>
  );
}
