import StatusPill from "@/components/StatusPill";
import {
  QA_STATUS_LABEL,
  QA_STATUS_TONE,
  countByStatus,
  formatDuration,
  formatTimestamp,
} from "@/lib/qa";
import type { QaRun } from "@/types/qa";

interface QaRunRowProps {
  run: QaRun;
  onSelect: (run: QaRun) => void;
}

export default function QaRunRow({ run, onSelect }: QaRunRowProps) {
  const counts = countByStatus(run.tests.map((test) => test.status));
  const observations = run.console_errors.length + run.network_failures.length;

  return (
    <button
      type="button"
      onClick={() => onSelect(run)}
      className="grid w-full grid-cols-1 items-center gap-3 border-b border-slate-800/70 px-4 py-3 text-left transition-colors last:border-b-0 hover:bg-slate-800/40 sm:grid-cols-[9rem_1fr_auto]"
    >
      <StatusPill tone={QA_STATUS_TONE[run.status]}>
        {QA_STATUS_LABEL[run.status]}
      </StatusPill>

      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-slate-100">{run.target_name}</p>
        <p className="truncate font-mono text-xs text-slate-500">{run.target_base_url}</p>
      </div>

      <div className="text-left sm:text-right">
        <p className="text-sm text-slate-300">
          {counts.passed}/{run.tests.length} passed
          {observations > 0 ? (
            <span className="text-amber-300/80"> &middot; {observations} obs</span>
          ) : null}
        </p>
        <p className="text-xs text-slate-500">
          {formatTimestamp(run.started_at)} &middot; {formatDuration(run.duration_ms)}
        </p>
      </div>
    </button>
  );
}
