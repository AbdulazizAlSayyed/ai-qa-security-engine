import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";

import ConnectionChain, { type ChainHop } from "@/components/ConnectionChain";
import PipelineOverview from "@/components/PipelineOverview";
import StatCard from "@/components/StatCard";
import StatusPill, { type Tone } from "@/components/StatusPill";
import Distribution from "@/components/dashboard/Distribution";
import HistoryTable from "@/components/dashboard/HistoryTable";
import { PRIORITY_SERIES, QA_SERIES, SEVERITY_SERIES } from "@/components/dashboard/series";
import TrendChart from "@/components/dashboard/TrendChart";
import { useDashboard } from "@/hooks/useDashboard";
import { useHealth } from "@/hooks/useHealth";
import { useTargets } from "@/hooks/useTargets";
import {
  ACTIVE_STATES,
  ASSESSMENT_LABEL,
  ASSESSMENT_TONE,
  assessableTargets as filterAssessable,
  formatTimestamp,
} from "@/lib/assessment";
import { config } from "@/lib/config";
import { startAssessment } from "@/services/assessments";
import type { Dashboard } from "@/types/dashboard";

const POLL_MS = 1500;
const TREND_RANGES = [7, 30, 90] as const;

function CardLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link
      to={to}
      className="block rounded-xl transition-transform hover:-translate-y-0.5 focus-visible:outline-2 focus-visible:outline-sky-400"
    >
      {children}
    </Link>
  );
}

function SummaryCards({ data }: { data: Dashboard }) {
  const a = data.assessments;
  const statusDetail = [
    `${a.completed} completed`,
    `${a.failed} failed`,
    a.running ? `${a.running} running` : null,
    a.analyzing ? `${a.analyzing} analyzing` : null,
    a.partial ? `${a.partial} partial` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5" aria-label="Summary">
      <CardLink to="/assessments">
        <StatCard label="Assessments" value={a.total} detail={statusDetail} />
      </CardLink>
      <CardLink to="/qa">
        <StatCard
          label="QA checks failed"
          value={data.qa.failed}
          detail={`of ${data.qa.total} checks run`}
          tone={data.qa.failed > 0 ? "negative" : "positive"}
        />
      </CardLink>
      <CardLink to="/security">
        <StatCard
          label="Security findings"
          value={data.security.total}
          detail={`${data.security.high} high · ${data.security.medium} medium`}
          tone={data.security.high > 0 ? "negative" : data.security.total > 0 ? "warning" : "positive"}
        />
      </CardLink>
      <CardLink to={data.latest ? `/assessments/${data.latest.id}#prioritized-issues` : "/assessments"}>
        <StatCard
          label="Prioritized issues"
          value={data.issues.by_priority.total}
          detail={`${data.issues.by_priority.P1} P1 · from ${a.correlated} correlated assessment${a.correlated === 1 ? "" : "s"}`}
          tone={data.issues.by_priority.P1 > 0 ? "negative" : "neutral"}
        />
      </CardLink>
      <CardLink to="/targets">
        <StatCard
          label="Targets"
          value={data.targets.enabled}
          detail={`enabled of ${data.targets.total} registered`}
        />
      </CardLink>
    </section>
  );
}

function LatestAssessment({ data }: { data: Dashboard }) {
  const latest = data.latest;
  if (!latest) return null;
  return (
    <section
      className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900/60 px-5 py-4"
      aria-label="Latest completed assessment"
    >
      <div className="min-w-0">
        <p className="text-xs tracking-wide text-slate-500 uppercase">Latest completed assessment</p>
        <p className="mt-0.5 text-sm text-slate-100">
          {latest.target_name}{" "}
          <span className="text-slate-500">· {formatTimestamp(latest.started_at ?? latest.created_at)}</span>
          {latest.partial ? <span className="ml-2 text-xs text-amber-300">Partial</span> : null}
        </p>
        <p className="mt-0.5 font-mono text-xs text-slate-500">
          QA {latest.qa.failed} failed of {latest.qa.total} · security {latest.security.total} findings ·{" "}
          {latest.correlation_status === "completed"
            ? `${latest.issues.total} issues (${latest.issues.P1} P1, ${latest.issues.P2} P2)`
            : "not correlated yet"}
        </p>
      </div>
      <div className="flex gap-2">
        <Link
          to={`/assessments/${latest.id}`}
          className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:border-slate-500 hover:bg-slate-800/60"
        >
          Open assessment
        </Link>
        <Link
          to={`/assessments/${latest.id}#prioritized-issues`}
          className="rounded-lg border border-sky-500/40 px-3 py-1.5 text-sm text-sky-300 hover:bg-sky-500/10"
        >
          {latest.correlation_status === "completed" ? "View issues" : "Correlate issues"}
        </Link>
      </div>
    </section>
  );
}

function Trends({
  data,
  trendDays,
  onTrendDays,
}: {
  data: Dashboard;
  trendDays: number;
  onTrendDays: (days: number) => void;
}) {
  return (
    <section aria-label="Trends">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-slate-200">Trends</h2>
          <p className="text-xs text-slate-500">
            Per UTC day of assessment start, last {data.trend_days} days. Only days with an
            assessment are shown.
          </p>
        </div>
        <div className="flex gap-1" role="group" aria-label="Trend range">
          {TREND_RANGES.map((days) => (
            <button
              key={days}
              type="button"
              onClick={() => onTrendDays(days)}
              aria-pressed={trendDays === days}
              className={`rounded-md px-2.5 py-1 text-xs transition-colors ${
                trendDays === days ? "bg-sky-500/15 text-sky-300" : "text-slate-400 hover:bg-slate-800/60"
              }`}
            >
              {days} days
            </button>
          ))}
        </div>
      </div>

      {data.trends.length === 0 ? (
        <p className="rounded-xl border border-dashed border-slate-800 p-6 text-center text-sm text-slate-500">
          No assessments in the last {data.trend_days} days.
        </p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <TrendChart
            title="Assessments"
            description="Completed, failed and still-running assessments per day."
            points={data.trends}
            series={[
              { key: "completed", label: "Completed", fill: "bg-emerald-400" },
              { key: "failed", label: "Failed", fill: "bg-rose-400" },
              { key: "other", label: "Running", fill: "bg-slate-500" },
            ]}
            value={(p, key) =>
              key === "completed"
                ? p.completed
                : key === "failed"
                  ? p.failed
                  : Math.max(p.assessments - p.completed - p.failed, 0)
            }
          />
          <TrendChart
            title="Security findings by tool severity"
            description="As reported by the scanners; severity is never re-scored."
            points={data.trends}
            series={SEVERITY_SERIES}
            value={(p, key) => p.security[key]}
          />
          <TrendChart
            title="QA check failures"
            description="Failed QA checks per day."
            points={data.trends}
            series={[{ key: "qa_failed", label: "Failed checks", fill: "bg-rose-400" }]}
            value={(p) => p.qa_failed}
          />
          <TrendChart
            title="Prioritized issues"
            description="Issues of correlated assessments, by Phase 6 priority."
            points={data.trends}
            series={PRIORITY_SERIES}
            value={(p, key) => p.issues[key]}
          />
        </div>
      )}
    </section>
  );
}

function SystemStatus({ health, error }: Pick<ReturnType<typeof useHealth>, "health" | "error">) {
  const apiReachable = health !== null;
  const dbConnected = health !== null && health.database.status === "connected";
  const hops: ChainHop[] = [
    {
      name: "React (Vite)",
      address: window.location.origin,
      tone: "positive",
      label: "Running",
      note: "This page rendered, so the bundle is being served.",
    },
    {
      name: "FastAPI",
      address: config.apiBaseUrl,
      tone: apiReachable ? "positive" : "negative",
      label: apiReachable ? "Reachable" : "No response",
      note: health ? `Service v${health.version}, ${health.environment} mode.` : (error ?? "Checking…"),
    },
    {
      name: "MongoDB",
      address: health ? `database "${health.database.database}"` : "mongodb://localhost:27017",
      tone: dbConnected ? "positive" : apiReachable ? "negative" : "neutral",
      label: dbConnected ? "Connected" : apiReachable ? "Unavailable" : "Unknown",
      note: health
        ? dbConnected
          ? `MongoDB ${health.database.server_version ?? "?"} answered in ${health.database.latency_ms ?? "?"} ms.`
          : (health.database.error ?? "MongoDB did not answer the ping.")
        : "The backend has not reported on the database yet.",
    },
  ];
  return (
    <details className="rounded-xl border border-slate-800 bg-slate-900/40 p-5">
      <summary className="cursor-pointer text-sm font-semibold text-slate-200">
        System status &amp; pipeline
      </summary>
      <div className="mt-4 flex flex-col gap-4">
        <ConnectionChain hops={hops} />
        <PipelineOverview />
      </div>
    </details>
  );
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const [trendDays, setTrendDays] = useState<number>(30);
  const [isRunning, setIsRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [selectedTargetId, setSelectedTargetId] = useState("");

  const { dashboard, error, isLoading, refresh } = useDashboard(trendDays, isRunning ? POLL_MS : null);
  const { targets, error: targetsError } = useTargets();
  const { health, error: healthError } = useHealth();

  const assessable = useMemo(() => filterAssessable(targets), [targets]);
  useEffect(() => {
    if (selectedTargetId || assessable.length === 0) return;
    setSelectedTargetId(assessable[0]?.id ?? "");
  }, [assessable, selectedTargetId]);

  /** The run started here, as MongoDB currently records it (real id and state). */
  const live = useMemo(
    () =>
      isRunning
        ? (dashboard?.history ?? []).find(
            (item) => item.target_id === selectedTargetId && ACTIVE_STATES.has(item.status),
          ) ?? null
        : null,
    [dashboard, isRunning, selectedTargetId],
  );

  const handleRun = useCallback(async () => {
    if (!selectedTargetId) return;
    setIsRunning(true);
    setRunError(null);
    try {
      // The existing pipeline: POST /assessments -> AssessmentService -> orchestrator.
      const assessment = await startAssessment(selectedTargetId);
      navigate(`/assessments/${assessment.id}`);
    } catch (caught) {
      setRunError(caught instanceof Error ? caught.message : "Could not start the assessment.");
      await refresh();
    } finally {
      setIsRunning(false);
    }
  }, [selectedTargetId, navigate, refresh]);

  const healthTone: Tone = health
    ? health.database.status === "connected"
      ? "positive"
      : "warning"
    : healthError
      ? "negative"
      : "neutral";

  const empty = dashboard !== null && dashboard.assessments.total === 0;

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Dashboard</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-400">
            Everything the platform has recorded, aggregated from the stored assessments, issues and
            targets. Open any number to reach the assessment, QA, security or target page behind it.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <StatusPill tone={healthTone}>
            {health
              ? health.database.status === "connected"
                ? "API & database online"
                : "Database unavailable"
              : healthError
                ? "Backend unreachable"
                : "Checking"}
          </StatusPill>
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={isLoading || isRunning}
            className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:bg-slate-800/60 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isLoading ? "Loading..." : "Refresh"}
          </button>
        </div>
      </header>

      <section
        className="rounded-xl border border-slate-800 bg-slate-900/60 p-5"
        aria-label="Run Full Assessment"
      >
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-64 flex-1">
            <label className="block text-sm font-medium text-slate-300" htmlFor="dashboard-target">
              Registered target
            </label>
            <select
              id="dashboard-target"
              value={selectedTargetId}
              onChange={(event) => setSelectedTargetId(event.target.value)}
              disabled={isRunning || assessable.length === 0}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 focus:border-sky-500 focus:outline-none disabled:opacity-50"
            >
              {assessable.length === 0 ? (
                <option value="">No assessable target</option>
              ) : (
                assessable.map((target) => (
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
          <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-sky-300" role="status">
            <span className="size-1.5 animate-pulse rounded-full bg-sky-400" />
            <span>Assessment started: QA engine, then security engine, then evidence normalization.</span>
            {live ? (
              <span className="flex items-center gap-2">
                <StatusPill tone={ASSESSMENT_TONE[live.status]} pulse>
                  {ASSESSMENT_LABEL[live.status]}
                </StatusPill>
                <Link to={`/assessments/${live.id}`} className="text-sky-300 underline hover:text-sky-200">
                  Follow it
                </Link>
              </span>
            ) : null}
          </div>
        ) : null}

        {targets !== null && assessable.length === 0 ? (
          <p className="mt-3 text-sm text-slate-400">
            No enabled web target is registered.{" "}
            <Link to="/targets" className="text-sky-300 hover:text-sky-200">
              Register one on the Targets page
            </Link>
            .
          </p>
        ) : null}
        {targetsError ? (
          <p className="mt-3 text-sm text-rose-300">Targets could not be loaded: {targetsError}</p>
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

      {error ? (
        <div role="alert" className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-5">
          <p className="font-medium text-rose-200">Unable to load the dashboard</p>
          <p className="mt-1 text-sm text-rose-200/80">{error}</p>
          {dashboard ? (
            <p className="mt-1 text-xs text-rose-200/60">Showing the last data that loaded.</p>
          ) : null}
        </div>
      ) : null}

      {dashboard === null && isLoading && !error ? (
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-10 text-center">
          <p className="text-sm text-slate-400">Loading dashboard...</p>
        </div>
      ) : null}

      {empty ? (
        <section
          className="rounded-xl border border-dashed border-slate-800 bg-slate-900/40 p-10 text-center"
          aria-label="No assessments yet"
        >
          <p className="font-medium text-slate-200">No assessments yet.</p>
          <ol className="mx-auto mt-3 max-w-md list-decimal space-y-1 pl-5 text-left text-sm text-slate-400">
            <li>
              {dashboard.targets.enabled > 0 ? (
                <>
                  {dashboard.targets.enabled} enabled target{dashboard.targets.enabled === 1 ? " is" : "s are"}{" "}
                  registered.
                </>
              ) : (
                <>
                  Register a target on the{" "}
                  <Link to="/targets" className="text-sky-300 hover:text-sky-200">
                    Targets
                  </Link>{" "}
                  page.
                </>
              )}
            </li>
            <li>Pick it above and choose Run Full Assessment.</li>
            <li>Its QA results, security findings and history will appear here.</li>
          </ol>
        </section>
      ) : null}

      {dashboard && !empty ? (
        <>
          <SummaryCards data={dashboard} />
          <LatestAssessment data={dashboard} />

          <div className="grid gap-4 lg:grid-cols-3">
            <Distribution
              title="Issue priority"
              description={`Stored Phase 6 issues across ${dashboard.issues.assessments_with_issues} assessment(s). Priority ranks the work; it is not a severity.`}
              series={PRIORITY_SERIES}
              counts={dashboard.issues.by_priority}
              to={dashboard.latest ? `/assessments/${dashboard.latest.id}#prioritized-issues` : undefined}
              linkLabel="Latest issues"
              footer={
                dashboard.assessments.correlated === 0
                  ? "No assessment has been correlated yet. Open an assessment and run Correlate & Prioritize."
                  : `${dashboard.issues.by_type.security ?? 0} security · ${dashboard.issues.by_type.qa ?? 0} QA`
              }
            />
            <Distribution
              title="Security findings"
              description="Totals over all assessments, by the scanner's own severity."
              series={SEVERITY_SERIES}
              counts={dashboard.security}
              to="/security"
              linkLabel="Security runs"
            />
            <Distribution
              title="QA results"
              description="QA checks over all assessments, by outcome."
              series={QA_SERIES}
              counts={dashboard.qa}
              to="/qa"
              linkLabel="QA runs"
              footer={
                dashboard.assessments.partial > 0
                  ? `${dashboard.assessments.partial} assessment(s) partial: one engine stage could not execute.`
                  : undefined
              }
            />
          </div>

          <Trends data={dashboard} trendDays={trendDays} onTrendDays={setTrendDays} />

          <section aria-label="Assessment history">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-200">
                Assessment history{" "}
                <span className="font-normal text-slate-500">
                  (latest {dashboard.history.length} of {dashboard.assessments.total})
                </span>
              </h2>
              <Link to="/assessments" className="text-xs text-sky-300 hover:text-sky-200">
                All assessments &rarr;
              </Link>
            </div>
            <HistoryTable history={dashboard.history} />
          </section>

          <p className="text-right font-mono text-[11px] text-slate-600">
            Aggregated {formatTimestamp(dashboard.generated_at)}
          </p>
        </>
      ) : null}

      <SystemStatus health={health} error={healthError} />
    </div>
  );
}
