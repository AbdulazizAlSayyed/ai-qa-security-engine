import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import StatCard from "@/components/StatCard";
import StatusPill from "@/components/StatusPill";
import AssessmentRow, { AssessmentListHeader } from "@/components/assessments/AssessmentRow";
import { useAssessments } from "@/hooks/useAssessments";
import { useTargets } from "@/hooks/useTargets";
import {
  ACTIVE_STATES,
  ASSESSMENT_LABEL,
  ASSESSMENT_TONE,
  assessableTargets as filterAssessable,
} from "@/lib/assessment";
import { startAssessment } from "@/services/assessments";

/** How often to re-read the list while a run is in flight. */
const POLL_MS = 1500;

export default function AssessmentsPage() {
  const navigate = useNavigate();
  const { targets, error: targetsError } = useTargets();

  const [selectedTargetId, setSelectedTargetId] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const {
    assessments,
    error: listError,
    isLoading,
    refresh,
  } = useAssessments(25, isRunning ? POLL_MS : null);

  const assessableTargets = useMemo(() => filterAssessable(targets), [targets]);

  useEffect(() => {
    if (selectedTargetId || assessableTargets.length === 0) return;
    setSelectedTargetId(assessableTargets[0]?.id ?? "");
  }, [assessableTargets, selectedTargetId]);

  /** The in-flight assessment as MongoDB currently records it. */
  const live = useMemo(
    () =>
      isRunning
        ? (assessments ?? []).find(
            (item) => item.target_id === selectedTargetId && ACTIVE_STATES.has(item.status),
          ) ?? null
        : null,
    [assessments, isRunning, selectedTargetId],
  );

  const handleRun = useCallback(async () => {
    if (!selectedTargetId) return;

    setIsRunning(true);
    setRunError(null);
    try {
      const assessment = await startAssessment(selectedTargetId);
      navigate(`/assessments/${assessment.id}`);
    } catch (caught) {
      setRunError(
        caught instanceof Error ? caught.message : "Could not start the assessment.",
      );
      await refresh();
    } finally {
      setIsRunning(false);
    }
  }, [selectedTargetId, refresh, navigate]);

  const totals = useMemo(() => {
    let evidence = 0;
    let findings = 0;
    let completed = 0;
    for (const item of assessments ?? []) {
      evidence += item.summary.evidence_total;
      findings += item.summary.total_findings;
      if (item.status === "completed") completed += 1;
    }
    return { evidence, findings, completed };
  }, [assessments]);

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Assessments</h1>
          <p className="mt-1 text-sm text-slate-400">
            One run of the whole pipeline: QA engine, then security engine, then evidence
            normalization. AI analysis of the evidence runs only when you request it on an
            assessment.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={isLoading || isRunning}
          className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:bg-slate-800/60 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isLoading ? "Loading..." : "Refresh"}
        </button>
      </header>

      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-64 flex-1">
            <label
              className="block text-sm font-medium text-slate-300"
              htmlFor="assessment-target"
            >
              Registered target
            </label>
            <select
              id="assessment-target"
              value={selectedTargetId}
              onChange={(event) => setSelectedTargetId(event.target.value)}
              disabled={isRunning || assessableTargets.length === 0}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 focus:border-sky-500 focus:outline-none disabled:opacity-50"
            >
              {assessableTargets.length === 0 ? (
                <option value="">No assessable target</option>
              ) : (
                assessableTargets.map((target) => (
                  <option key={target.id} value={target.id}>
                    {target.name} &mdash; {target.base_url}
                  </option>
                ))
              )}
            </select>
          </div>

          <button
            type="button"
            onClick={() => void handleRun()}
            disabled={isRunning || !selectedTargetId}
            className="rounded-lg bg-sky-500 px-5 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isRunning ? "Running pipeline..." : "Run Full Assessment"}
          </button>
        </div>

        {isRunning ? (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-sky-300">
            <span className="size-1.5 animate-pulse rounded-full bg-sky-400" />
            <span>Running a real browser and a baseline scan end to end.</span>
            {live ? (
              <span className="flex items-center gap-2">
                <span className="text-slate-500">Current state:</span>
                <StatusPill tone={ASSESSMENT_TONE[live.status]} pulse>
                  {ASSESSMENT_LABEL[live.status]}
                </StatusPill>
              </span>
            ) : null}
          </div>
        ) : null}

        {assessableTargets.length === 0 && targets !== null ? (
          <p className="mt-3 text-sm text-slate-400">
            No enabled web target is registered. Add one on the Targets page first.
          </p>
        ) : null}

        {runError ? (
          <p
            role="alert"
            className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-sm text-rose-200"
          >
            {runError}
          </p>
        ) : null}
      </section>

      {targetsError ? (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-5">
          <p className="font-medium text-rose-200">Unable to load targets</p>
          <p className="mt-1 text-sm text-rose-200/80">Please make sure the backend is running.</p>
        </div>
      ) : null}

      {listError ? (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-5">
          <p className="font-medium text-rose-200">Unable to load assessments</p>
          <p className="mt-1 text-sm text-rose-200/80">Please make sure the backend is running.</p>
          <p className="mt-2 font-mono text-xs text-rose-200/60">{listError}</p>
        </div>
      ) : null}

      {assessments && assessments.length > 0 ? (
        <section className="grid gap-4 sm:grid-cols-3">
          <StatCard
            label="Assessments"
            value={assessments.length}
            detail={`${totals.completed} completed`}
          />
          <StatCard label="Evidence records" value={totals.evidence} />
          <StatCard
            label="Findings"
            value={totals.findings}
            detail="Failed QA checks + security findings"
            tone={totals.findings > 0 ? "warning" : "positive"}
          />
        </section>
      ) : null}

      <section>
        <h2 className="mb-2 text-sm font-semibold text-slate-200">Recent assessments</h2>

        {isLoading && assessments === null ? (
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-10 text-center">
            <p className="text-sm text-slate-400">Loading assessments...</p>
          </div>
        ) : null}

        {assessments && assessments.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-800 bg-slate-900/40 p-10 text-center">
            <p className="font-medium text-slate-200">No assessments yet.</p>
            <p className="mt-1 text-sm text-slate-400">
              Pick a registered target and run the full pipeline to collect your first
              unified evidence set.
            </p>
          </div>
        ) : null}

        {assessments && assessments.length > 0 ? (
          <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/60">
            <AssessmentListHeader />
            {assessments.map((assessment) => (
              <AssessmentRow key={assessment.id} assessment={assessment} />
            ))}
          </div>
        ) : null}
      </section>
    </div>
  );
}
