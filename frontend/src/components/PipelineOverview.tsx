interface Stage {
  name: string;
  phase: string;
  live: boolean;
}

const STAGES: Stage[] = [
  { name: "Target registry", phase: "Phase 1", live: true },
  { name: "QA engine", phase: "Phase 2", live: true },
  { name: "Security engine", phase: "Phase 3", live: true },
  { name: "Orchestration", phase: "Phase 4", live: true },
  { name: "Evidence normalization", phase: "Phase 4", live: true },
  { name: "AI analysis", phase: "Phase 5", live: true },
  { name: "Correlation & prioritization", phase: "Phase 6", live: true },
  { name: "Dashboard & trends", phase: "Phase 7", live: true },
  { name: "Recommendations", phase: "Phase 8", live: false },
  { name: "Retest", phase: "Phase 9", live: false },
];

/**
 * The assessment pipeline, shown as a roadmap rather than as data.
 *
 * Nothing here reports a count or a result, because a stage being wired is
 * not the same as a stage having run. Showing invented numbers would defeat
 * the point of a platform whose entire premise is evidence that a tool
 * actually produced.
 */
export default function PipelineOverview() {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
      <h2 className="text-sm font-semibold text-slate-200">Assessment pipeline</h2>
      <p className="mt-1 text-sm text-slate-400">
        Stages light up as their phase lands. AI analysis and correlation run only when you
        request them on an assessment; recommendations and retest do not exist yet.
      </p>

      <ul className="mt-4 grid gap-2 sm:grid-cols-2">
        {STAGES.map((stage) => (
          <li
            key={stage.name}
            className="flex items-center justify-between rounded-lg border border-slate-800/70 bg-slate-950/40 px-4 py-2.5"
          >
            <span className={stage.live ? "text-slate-100" : "text-slate-500"}>{stage.name}</span>
            <span className="font-mono text-xs text-slate-600">{stage.phase}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
