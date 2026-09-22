import { useCallback, useEffect, useMemo, useState } from "react";

import Modal from "@/components/Modal";
import StatCard from "@/components/StatCard";
import QaRunDetails from "@/components/qa/QaRunDetails";
import QaRunRow from "@/components/qa/QaRunRow";
import { useQaRuns } from "@/hooks/useQaRuns";
import { useTargets } from "@/hooks/useTargets";
import { QA_STATUS_LABEL, countByStatus } from "@/lib/qa";
import { startQaRun } from "@/services/qa";
import type { QaRun } from "@/types/qa";

/** Only a browser-drivable target can be smoke-tested. */
const RUNNABLE_TYPES = new Set(["web_application", "web_and_api"]);

export default function QaPage() {
  const { targets, error: targetsError } = useTargets();
  const { runs, error: runsError, isLoading, refresh } = useQaRuns();

  const [selectedTargetId, setSelectedTargetId] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [openRun, setOpenRun] = useState<QaRun | null>(null);

  const runnableTargets = useMemo(
    () =>
      (targets ?? []).filter(
        (target) => target.enabled && RUNNABLE_TYPES.has(target.type) && target.base_url,
      ),
    [targets],
  );

  // Default to the first runnable target once they load.
  useEffect(() => {
    if (selectedTargetId || runnableTargets.length === 0) return;
    setSelectedTargetId(runnableTargets[0]?.id ?? "");
  }, [runnableTargets, selectedTargetId]);

  const handleRun = useCallback(async () => {
    if (!selectedTargetId) return;

    setIsRunning(true);
    setRunError(null);
    setNotice(null);
    try {
      const run = await startQaRun(selectedTargetId);
      setNotice(
        `Run finished for "${run.target_name}": ${QA_STATUS_LABEL[run.status].toLowerCase()}.`,
      );
      await refresh();
      setOpenRun(run);
    } catch (caught) {
      setRunError(caught instanceof Error ? caught.message : "Could not start the QA run.");
    } finally {
      setIsRunning(false);
    }
  }, [selectedTargetId, refresh]);

  const statusCounts = countByStatus((runs ?? []).map((run) => run.status));

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">QA Engine</h1>
          <p className="mt-1 text-sm text-slate-400">
            Drives a real browser through a generic smoke suite against a registered target.
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
            <label className="block text-sm font-medium text-slate-300" htmlFor="qa-target">
              Target
            </label>
            <select
              id="qa-target"
              value={selectedTargetId}
              onChange={(event) => setSelectedTargetId(event.target.value)}
              disabled={isRunning || runnableTargets.length === 0}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 focus:border-sky-500 focus:outline-none disabled:opacity-50"
            >
              {runnableTargets.length === 0 ? (
                <option value="">No runnable target</option>
              ) : (
                runnableTargets.map((target) => (
                  <option key={target.id} value={target.id}>
                    {target.name} — {target.base_url}
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
            {isRunning ? "Running..." : "Run QA"}
          </button>
        </div>

        {isRunning ? (
          <p className="mt-3 flex items-center gap-2 text-sm text-sky-300">
            <span className="size-1.5 animate-pulse rounded-full bg-sky-400" />
            Launching a browser and executing the smoke suite. This takes a few seconds.
          </p>
        ) : null}

        {runnableTargets.length === 0 && targets !== null ? (
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

      {notice ? (
        <div className="flex items-start justify-between gap-4 rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-4 py-3">
          <p className="text-sm text-emerald-200">{notice}</p>
          <button
            type="button"
            onClick={() => setNotice(null)}
            aria-label="Dismiss"
            className="text-emerald-300/70 hover:text-emerald-200"
          >
            &times;
          </button>
        </div>
      ) : null}

      {targetsError ? (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-5">
          <p className="font-medium text-rose-200">Unable to load targets</p>
          <p className="mt-1 text-sm text-rose-200/80">
            Please make sure the backend is running.
          </p>
        </div>
      ) : null}

      {runsError ? (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-5">
          <p className="font-medium text-rose-200">Unable to load QA runs</p>
          <p className="mt-1 text-sm text-rose-200/80">
            Please make sure the backend is running.
          </p>
          <p className="mt-2 font-mono text-xs text-rose-200/60">{runsError}</p>
        </div>
      ) : null}

      {runs && runs.length > 0 ? (
        <section className="grid gap-4 sm:grid-cols-3">
          <StatCard label="Runs" value={runs.length} />
          <StatCard
            label="Passed"
            value={statusCounts.passed}
            tone={statusCounts.passed > 0 ? "positive" : "neutral"}
          />
          <StatCard
            label="Failed"
            value={statusCounts.failed + statusCounts.error}
            tone={statusCounts.failed + statusCounts.error > 0 ? "negative" : "neutral"}
          />
        </section>
      ) : null}

      <section>
        <h2 className="mb-2 text-sm font-semibold text-slate-200">Recent runs</h2>

        {isLoading && runs === null ? (
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-10 text-center">
            <p className="text-sm text-slate-400">Loading runs...</p>
          </div>
        ) : null}

        {runs && runs.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-800 bg-slate-900/40 p-10 text-center">
            <p className="font-medium text-slate-200">No QA runs yet.</p>
            <p className="mt-1 text-sm text-slate-400">
              Pick a target and run the smoke suite to collect your first evidence.
            </p>
          </div>
        ) : null}

        {runs && runs.length > 0 ? (
          <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60">
            {runs.map((run) => (
              <QaRunRow key={run.id} run={run} onSelect={setOpenRun} />
            ))}
          </div>
        ) : null}
      </section>

      {openRun ? (
        <Modal
          title="QA run"
          subtitle={`${openRun.target_name} — ${QA_STATUS_LABEL[openRun.status]}`}
          onClose={() => setOpenRun(null)}
        >
          <QaRunDetails run={openRun} onClose={() => setOpenRun(null)} />
        </Modal>
      ) : null}
    </div>
  );
}
