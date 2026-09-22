import StatusPill from "@/components/StatusPill";
import SeverityBadge from "@/components/security/SeverityBadge";
import {
  RUN_STATUS_LABEL,
  RUN_STATUS_TONE,
  formatDuration,
  formatTimestamp,
} from "@/lib/security";
import { SEVERITIES, type SecurityRun } from "@/types/security";

interface SecurityRunRowProps {
  run: SecurityRun;
  onSelect: (run: SecurityRun) => void;
}

export default function SecurityRunRow({ run, onSelect }: SecurityRunRowProps) {
  return (
    <button
      type="button"
      onClick={() => onSelect(run)}
      className="grid w-full grid-cols-1 items-center gap-3 border-b border-slate-800/70 px-4 py-3 text-left transition-colors last:border-b-0 hover:bg-slate-800/40 sm:grid-cols-[10rem_1fr_auto]"
    >
      <StatusPill tone={RUN_STATUS_TONE[run.status]}>
        {RUN_STATUS_LABEL[run.status]}
      </StatusPill>

      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-slate-100">{run.target_name}</p>
        <p className="truncate font-mono text-xs text-slate-500">{run.target_base_url}</p>
      </div>

      <div className="flex flex-col items-start gap-1.5 sm:items-end">
        <div className="flex flex-wrap gap-1.5">
          {run.summary.total_findings === 0 ? (
            <span className="text-xs text-slate-500">No findings</span>
          ) : (
            SEVERITIES.filter((severity) => run.summary[severity] > 0).map((severity) => (
              <SeverityBadge
                key={severity}
                severity={severity}
                count={run.summary[severity]}
              />
            ))
          )}
        </div>
        <p className="text-xs text-slate-500">
          {formatTimestamp(run.started_at)} &middot; {formatDuration(run.duration_ms)}
        </p>
      </div>
    </button>
  );
}
