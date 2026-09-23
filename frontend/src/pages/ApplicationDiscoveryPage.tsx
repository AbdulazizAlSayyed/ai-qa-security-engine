import { useCallback, useEffect, useMemo, useState } from "react";

import Modal from "@/components/Modal";
import ApplicationMapView from "@/components/discovery/ApplicationMapView";
import PageDetails from "@/components/discovery/PageDetails";
import { useTargets } from "@/hooks/useTargets";
import {
  getApplicationMap,
  getDiscovery,
  listDiscoveries,
  startDiscovery,
} from "@/services/discoveries";
import type { ApplicationMap, DiscoveredPage, DiscoveryRun } from "@/types/discovery";

/** Only a browser-drivable target can be explored. */
const DISCOVERABLE_TYPES = new Set(["web_application", "web_and_api"]);

export default function ApplicationDiscoveryPage() {
  const { targets, error: targetsError } = useTargets();

  const [targetId, setTargetId] = useState("");
  const [authenticated, setAuthenticated] = useState(false);
  const [runs, setRuns] = useState<DiscoveryRun[] | null>(null);
  const [map, setMap] = useState<ApplicationMap | null>(null);
  const [openPage, setOpenPage] = useState<DiscoveredPage | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const discoverable = useMemo(
    () =>
      (targets ?? []).filter(
        (target) =>
          target.enabled && DISCOVERABLE_TYPES.has(target.type) && target.base_url,
      ),
    [targets],
  );
  const target = discoverable.find((candidate) => candidate.id === targetId);

  useEffect(() => {
    if (targetId || discoverable.length === 0) return;
    setTargetId(discoverable[0]?.id ?? "");
  }, [discoverable, targetId]);

  const load = useCallback(async () => {
    if (!targetId) {
      setRuns(null);
      setMap(null);
      return;
    }
    setIsLoading(true);
    try {
      const listed = await listDiscoveries(targetId);
      setRuns(listed);
      setMap(listed.length > 0 ? await getApplicationMap(targetId) : null);
      setError(null);
    } catch (caught) {
      setRuns(null);
      setMap(null);
      setError(caught instanceof Error ? caught.message : "Could not load discoveries.");
    } finally {
      setIsLoading(false);
    }
  }, [targetId]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleRun = useCallback(async () => {
    if (!targetId) return;
    setIsRunning(true);
    setError(null);
    try {
      const result = await startDiscovery(targetId, { authenticated });
      setMap(result);
      setRuns(await listDiscoveries(targetId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Discovery could not start.");
    } finally {
      setIsRunning(false);
    }
  }, [targetId, authenticated]);

  const openRun = useCallback(
    async (run: DiscoveryRun) => {
      try {
        setMap(await getDiscovery(run.target_id, run.discovery_id));
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Could not load that run.");
      }
    },
    [],
  );

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Application discovery</h1>
          <p className="mt-1 text-sm text-slate-400">
            Walks a target with a real browser and records what is actually there — pages,
            links, forms and controls. It reads; it never submits anything.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={isLoading || isRunning || !targetId}
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
              htmlFor="discovery-target"
            >
              Target
            </label>
            <select
              id="discovery-target"
              value={targetId}
              onChange={(event) => setTargetId(event.target.value)}
              disabled={isRunning || discoverable.length === 0}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 focus:border-sky-500 focus:outline-none disabled:opacity-50"
            >
              {discoverable.length === 0 ? (
                <option value="">No discoverable target</option>
              ) : (
                discoverable.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} — {item.base_url}
                  </option>
                ))
              )}
            </select>
          </div>

          <label className="flex items-center gap-2 pb-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={authenticated}
              onChange={(event) => setAuthenticated(event.target.checked)}
              disabled={isRunning}
              className="size-4 accent-sky-400"
            />
            Sign in first
          </label>

          <button
            type="button"
            onClick={() => void handleRun()}
            disabled={isRunning || !targetId}
            className="rounded-lg bg-sky-500 px-5 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isRunning ? "Exploring..." : "Run discovery"}
          </button>
        </div>

        {isRunning ? (
          <p className="mt-3 flex items-center gap-2 text-sm text-sky-300">
            <span className="size-1.5 animate-pulse rounded-full bg-sky-400" />
            A browser is walking {target?.base_url}. This takes as long as the crawl takes.
          </p>
        ) : null}

        <p className="mt-3 text-xs text-slate-500">
          Signing in uses the target&apos;s authentication profile and one of its enabled
          test accounts. When that is not configured, discovery runs anonymously and says
          exactly what was missing — it is never reported as authenticated.
        </p>

        {discoverable.length === 0 && targets !== null ? (
          <p className="mt-3 text-sm text-slate-400">
            No enabled web target is registered. Add one on the Targets page first.
          </p>
        ) : null}
      </section>

      {targetsError ? (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-5">
          <p className="font-medium text-rose-200">Unable to load targets</p>
          <p className="mt-1 text-sm text-rose-200/80">Is the backend running?</p>
        </div>
      ) : null}

      {error ? (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-5">
          <p className="font-medium text-rose-200">Discovery problem</p>
          <p className="mt-2 font-mono text-xs text-rose-200/70">{error}</p>
        </div>
      ) : null}

      {runs && runs.length > 1 ? (
        <section>
          <h3 className="mb-2 text-sm font-semibold text-slate-200">Previous runs</h3>
          <div className="flex flex-wrap gap-2">
            {runs.map((run) => (
              <button
                key={run.id}
                type="button"
                onClick={() => void openRun(run)}
                className={`rounded-lg border px-3 py-1.5 text-xs transition-colors ${
                  map?.discovery_id === run.discovery_id
                    ? "border-sky-500/50 bg-sky-500/10 text-sky-200"
                    : "border-slate-700 text-slate-300 hover:bg-slate-800/60"
                }`}
              >
                {new Date(run.started_at).toLocaleString()} · {run.summary.pages} pages ·{" "}
                {run.status}
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {map ? (
        <ApplicationMapView map={map} onOpenPage={setOpenPage} />
      ) : runs && runs.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-800 bg-slate-900/40 p-10 text-center">
          <p className="font-medium text-slate-200">No discovery has run for this target.</p>
          <p className="mt-1 text-sm text-slate-400">
            Run one to find out what the application actually contains.
          </p>
        </div>
      ) : null}

      {openPage ? (
        <Modal
          title={openPage.path}
          subtitle={openPage.title || undefined}
          onClose={() => setOpenPage(null)}
        >
          <PageDetails page={openPage} onClose={() => setOpenPage(null)} />
        </Modal>
      ) : null}
    </div>
  );
}
