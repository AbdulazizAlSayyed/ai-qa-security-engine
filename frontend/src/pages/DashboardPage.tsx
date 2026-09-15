import ConnectionChain, { type ChainHop } from "@/components/ConnectionChain";
import PipelineOverview from "@/components/PipelineOverview";
import StatCard from "@/components/StatCard";
import StatusPill, { type Tone } from "@/components/StatusPill";
import { useHealth } from "@/hooks/useHealth";
import { config } from "@/lib/config";

const START_BACKEND_COMMAND =
  "cd backend\n.\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000";

function formatTime(value: Date | null): string {
  return value ? value.toLocaleTimeString() : "never";
}

export default function DashboardPage() {
  const { health, error, isChecking, lastCheckedAt, refresh } = useHealth();

  const apiReachable = health !== null;
  const dbConnected = health !== null && health.database.status === "connected";

  const overallTone: Tone = error ? "negative" : dbConnected ? "positive" : "warning";
  const overallLabel = error
    ? "Backend unreachable"
    : dbConnected
      ? "All systems operational"
      : health !== null
        ? "Degraded"
        : "Checking";

  const apiNote = health
    ? `Service v${health.version}, ${health.environment} mode.`
    : "Start uvicorn on 127.0.0.1:8000.";

  const dbNote = health
    ? health.database.status === "connected"
      ? `MongoDB ${health.database.server_version ?? "?"} answered a ping in ${health.database.latency_ms ?? "?"} ms.`
      : (health.database.error ?? "MongoDB did not answer the ping.")
    : "The backend has not reported on the database yet.";

  const hops: ChainHop[] = [
    {
      name: "React (Vite)",
      address: window.location.origin,
      tone: "positive",
      label: "Running",
      note: "This page rendered, so the dev server is serving the bundle.",
    },
    {
      name: "FastAPI",
      address: config.apiBaseUrl,
      tone: apiReachable ? "positive" : "negative",
      label: apiReachable ? "Reachable" : "No response",
      note: apiNote,
    },
    {
      name: "MongoDB",
      address: health ? `database "${health.database.database}"` : "mongodb://localhost:27017",
      tone: dbConnected ? "positive" : apiReachable ? "negative" : "neutral",
      label: dbConnected ? "Connected" : apiReachable ? "Unavailable" : "Unknown",
      note: dbNote,
    },
  ];

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">System status</h1>
          <p className="mt-1 text-sm text-slate-400">
            Phase 0 &mdash; scaffolding verified against live services.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <StatusPill tone={overallTone} pulse={isChecking}>
            {overallLabel}
          </StatusPill>
          <button
            type="button"
            onClick={refresh}
            disabled={isChecking}
            className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:bg-slate-800/60 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isChecking ? "Checking..." : "Re-check"}
          </button>
        </div>
      </header>

      {error ? (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-5">
          <p className="font-medium text-rose-200">Cannot reach the backend</p>
          <p className="mt-1 text-sm text-rose-200/80">{error}</p>
          <pre className="mt-3 overflow-x-auto rounded-lg bg-slate-950/70 p-3 font-mono text-xs text-slate-300">
            {START_BACKEND_COMMAND}
          </pre>
        </div>
      ) : null}

      <section className="grid gap-4 sm:grid-cols-3">
        <StatCard
          label="API"
          value={apiReachable ? "Online" : "Offline"}
          detail={health ? `v${health.version}` : config.apiBaseUrl}
          tone={apiReachable ? "positive" : "negative"}
        />
        <StatCard
          label="Database"
          value={dbConnected ? "Connected" : apiReachable ? "Unavailable" : "Unknown"}
          detail={
            health && health.database.status === "connected"
              ? `MongoDB ${health.database.server_version ?? "?"} - ${health.database.latency_ms ?? "?"} ms`
              : "No successful ping"
          }
          tone={dbConnected ? "positive" : apiReachable ? "negative" : "neutral"}
        />
        <StatCard
          label="Environment"
          value={health?.environment ?? "unknown"}
          detail={`Last checked ${formatTime(lastCheckedAt)}`}
        />
      </section>

      <ConnectionChain hops={hops} />
      <PipelineOverview />
    </div>
  );
}
