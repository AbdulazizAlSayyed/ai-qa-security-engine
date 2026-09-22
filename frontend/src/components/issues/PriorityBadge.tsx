import type { Priority } from "@/types/issues";

const PRIORITY_CLASS: Record<Priority, string> = {
  P1: "bg-rose-500/20 text-rose-100 ring-rose-400/50",
  P2: "bg-orange-500/15 text-orange-200 ring-orange-400/40",
  P3: "bg-sky-500/10 text-sky-200 ring-sky-400/30",
  P4: "bg-slate-500/10 text-slate-300 ring-slate-500/30",
};

interface PriorityBadgeProps {
  priority: Priority;
  score?: number;
}

/** Derived priority. Deliberately styled unlike SeverityBadge: it is not a severity. */
export default function PriorityBadge({ priority, score }: PriorityBadgeProps) {
  return (
    <span
      title="Derived priority (not a scanner severity)"
      className={`inline-flex items-center gap-1.5 rounded px-1.5 py-0.5 font-mono text-xs font-semibold ring-1 ring-inset ${PRIORITY_CLASS[priority]}`}
    >
      {priority}
      {score !== undefined ? <span className="font-normal opacity-70">{score}</span> : null}
    </span>
  );
}
