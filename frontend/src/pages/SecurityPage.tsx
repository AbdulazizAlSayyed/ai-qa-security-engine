import { useCallback, useEffect, useMemo, useState } from "react";

import Modal from "@/components/Modal";
import StatCard from "@/components/StatCard";
import SecurityRunDetails from "@/components/security/SecurityRunDetails";
import SecurityRunRow from "@/components/security/SecurityRunRow";
import SeverityBadge from "@/components/security/SeverityBadge";
import { useSecurityRuns } from "@/hooks/useSecurityRuns";
import { useTargets } from "@/hooks/useTargets";
import { RUN_STATUS_LABEL } from "@/lib/security";
import { startSecurityRun } from "@/services/security";
import { SEVERITIES, type SecurityRun, type Severity } from "@/types/security";

/** ZAP drives a browser-facing scan, so a UI surface must exist. */
const SCANNABLE_TYPES = new Set(["web_application", "web_and_api"]);

export default function SecurityPage() {
  const { targets, error: targetsError } = useTargets();
  const { runs, error: runsError, isLoading, refresh } = useSecurityRuns();

  const [selectedTargetId, setSelectedTargetId] = useState("");
  const [isScanning, setIsScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [openRun, setOpenRun] = useState<SecurityRun | null>(null);

  const scannableTargets = useMemo(
    () =>
      (targets ?? []).filter(
        (target) => target.enabled && SCANNABLE_TYPES.has(target.type) && target.base_url,
      ),
    [targets],
  );

  useEffect(() => {
    if (selectedTargetId || scannableTargets.length === 0) return;
    setSelectedTargetId(scannableTargets[0]?.id ?? "");
  }, [scannableTargets, selectedTargetId]);

  const handleScan = useCallback(async () => {
    if (!selectedTargetId) return;

    setIsScanning(true);
    setScanError(null);
    setNotice(null);
    try {
      const run = await startSecurityRun(selectedTargetId);
      setNotice(
        `Scan ${RUN_STATUS_LABEL[run.status].toLowerCase()} for "${run.target_name}": ` +
          `${run.summary.total_findings} finding${run.summary.total_findings === 1 ? "" : "s"}.`,
      );
      await refresh();
      setOpenRun(run);
    } catch (caught) {
      setScanError(
        caught instanceof Error ? caught.message : "Could not start the security scan.",
      );
    } finally {
      setIsScanning(false);
    }
  }, [selectedTargetId, refresh]);

  const totals = useMemo(() => {
    const counts: Record<Severity, number> = { high: 0, medium: 0, low: 0, informational: 0 };
    for (const run of runs ?? []) {
      for (const severity of SEVERITIES) counts[severity] += run.summary[severity];
    }
    return counts;
  }, [runs]);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Security Engine</h1>
          <p className="mt-1 text-sm text-slate-400">
            Controlled, non-destructive assessment of a registered target with OWASP ZAP
            and custom API probes.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={isLoading || isScanning}
          className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:bg-slate-800/60 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isLoading ? "Loading..." : "Refresh"}
        </button>
      </header>

      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-64 flex-1">
            <label className="block text-sm font-medium text-slate-300" htmlFor="security-target">
              Target
            </label>
            <select
              id="security-target"
              value={selectedTargetId}
              onChange={(event) => setSelectedTargetId(event.target.value)}
              disabled={isScanning || scannableTargets.length === 0}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 focus:border-sky-500 focus:outline-none disabled:opacity-50"
            >
              {scannableTargets.length === 0 ? (
                <option value="">No scannable target</option>
              ) : (
                scannableTargets.map((target) => (
                  <option key={target.id} value={target.id}>
                    {target.name} — {target.base_url}
                  </option>
                ))
              )}
            </select>
          </div>

          <button
            type="button"
            onClick={() => void handleScan()}
            disabled={isScanning || !selectedTargetId}
            className="rounded-lg bg-sky-500 px-5 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isScanning ? "Scanning..." : "Run Security Scan"}
          </button>
        </div>

        {isScanning ? (
          <p className="mt-3 flex items-center gap-2 text-sm text-sky-300">
            <span className="size-1.5 animate-pulse rounded-full bg-sky-400" />
            Running a baseline scan. Passive rules and API probes only &mdash; nothing
            destructive is sent.
          </p>
        ) : null}

        {scannableTargets.length === 0 && targets !== null ? (
          <p className="mt-3 text-sm text-slate-400">
            No enabled web target is registered. Add one on the Targets page first.
          </p>
        ) : null}

        {scanError ? (
          <p
            role="alert"
            className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-sm text-rose-200"
          >
            {scanError}
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
          <p className="font-medium text-rose-200">Unable to load security runs</p>
          <p className="mt-1 text-sm text-rose-200/80">
            Please make sure the backend is running.
          </p>
          <p className="mt-2 font-mono text-xs text-rose-200/60">{runsError}</p>
        </div>
      ) : null}

      {runs && runs.length > 0 ? (
        <>
          <section className="grid gap-4 sm:grid-cols-3">
            <StatCard label="Scans" value={runs.length} />
            <StatCard
              label="High severity"
              value={totals.high}
              tone={totals.high > 0 ? "negative" : "positive"}
            />
            <StatCard
              label="Medium severity"
              value={totals.medium}
              tone={totals.medium > 0 ? "warning" : "positive"}
            />
          </section>

          <section className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3">
            <span className="text-xs tracking-wide text-slate-500 uppercase">
              All findings
            </span>
            {SEVERITIES.map((severity) => (
              <SeverityBadge key={severity} severity={severity} count={totals[severity]} />
            ))}
          </section>
        </>
      ) : null}

      <section>
        <h2 className="mb-2 text-sm font-semibold text-slate-200">Recent security runs</h2>

        {isLoading && runs === null ? (
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-10 text-center">
            <p className="text-sm text-slate-400">Loading runs...</p>
          </div>
        ) : null}

        {runs && runs.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-800 bg-slate-900/40 p-10 text-center">
            <p className="font-medium text-slate-200">No security runs yet.</p>
            <p className="mt-1 text-sm text-slate-400">
              Pick a registered target and run a baseline scan to collect your first
              security evidence.
            </p>
          </div>
        ) : null}

        {runs && runs.length > 0 ? (
          <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60">
            {runs.map((run) => (
              <SecurityRunRow key={run.id} run={run} onSelect={setOpenRun} />
            ))}
          </div>
        ) : null}
      </section>

      {openRun ? (
        <Modal
          title="Security run"
          subtitle={`${openRun.target_name} — ${openRun.summary.total_findings} findings`}
          onClose={() => setOpenRun(null)}
        >
          <SecurityRunDetails run={openRun} onClose={() => setOpenRun(null)} />
        </Modal>
      ) : null}
    </div>
  );
}
