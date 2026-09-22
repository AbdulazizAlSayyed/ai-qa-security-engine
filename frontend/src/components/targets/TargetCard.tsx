import StatusPill from "@/components/StatusPill";
import { TARGET_TYPE_LABELS, type Target } from "@/types/target";

interface TargetCardProps {
  target: Target;
  onView: (target: Target) => void;
  onEdit: (target: Target) => void;
  onDelete: (target: Target) => void;
}

function UrlRow({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="min-w-0">
      <p className="text-xs tracking-wide text-slate-500 uppercase">{label}</p>
      {value ? (
        <a
          href={value}
          target="_blank"
          rel="noreferrer noopener"
          className="font-mono text-sm break-all text-sky-300 hover:text-sky-200 hover:underline"
        >
          {value}
        </a>
      ) : (
        <p className="font-mono text-sm text-slate-600">not set</p>
      )}
    </div>
  );
}

export default function TargetCard({ target, onView, onEdit, onDelete }: TargetCardProps) {
  return (
    <article className="flex flex-col rounded-xl border border-slate-800 bg-slate-900/60 p-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-lg font-semibold text-slate-100">{target.name}</h3>
          <p className="text-sm text-slate-400">{TARGET_TYPE_LABELS[target.type]}</p>
        </div>
        <StatusPill tone={target.enabled ? "positive" : "neutral"}>
          {target.enabled ? "Enabled" : "Disabled"}
        </StatusPill>
      </header>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <UrlRow label="Frontend" value={target.base_url} />
        <UrlRow label="API" value={target.api_url} />
      </div>

      {target.description ? (
        <p className="mt-4 text-sm text-slate-400">{target.description}</p>
      ) : null}

      <footer className="mt-5 flex flex-wrap gap-2 border-t border-slate-800 pt-4">
        <button
          type="button"
          onClick={() => onView(target)}
          className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:bg-slate-800/60"
        >
          Details
        </button>
        <button
          type="button"
          onClick={() => onEdit(target)}
          className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:bg-slate-800/60"
        >
          Edit
        </button>
        <button
          type="button"
          onClick={() => onDelete(target)}
          className="rounded-lg border border-rose-500/40 px-3 py-1.5 text-sm text-rose-300 transition-colors hover:border-rose-500/70 hover:bg-rose-500/10"
        >
          Delete
        </button>
      </footer>
    </article>
  );
}
