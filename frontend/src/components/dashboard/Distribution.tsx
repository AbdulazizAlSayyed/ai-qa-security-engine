import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import type { SeriesDef } from "@/components/dashboard/series";

interface DistributionProps<K extends string> {
  title: string;
  description: ReactNode;
  series: SeriesDef<K>[];
  counts: Record<K, number>;
  /** Where the whole panel drills down to (an existing page). */
  to?: string;
  linkLabel?: string;
  footer?: ReactNode;
}

/** One horizontal stacked bar plus a legend with exact counts. */
export default function Distribution<K extends string>({
  title,
  description,
  series,
  counts,
  to,
  linkLabel,
  footer,
}: DistributionProps<K>) {
  const total = series.reduce((sum, item) => sum + (counts[item.key] ?? 0), 0);

  return (
    <section
      className="flex flex-col rounded-xl border border-slate-800 bg-slate-900/60 p-5"
      aria-label={title}
    >
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-200">{title}</h2>
        {to ? (
          <Link to={to} className="text-xs whitespace-nowrap text-sky-300 hover:text-sky-200">
            {linkLabel ?? "Open"} &rarr;
          </Link>
        ) : null}
      </div>
      <p className="mt-1 text-xs text-slate-500">{description}</p>

      <div
        className="mt-4 flex h-2.5 w-full overflow-hidden rounded-full bg-slate-800"
        role="img"
        aria-label={`${title}: ${series.map((s) => `${s.label} ${counts[s.key] ?? 0}`).join(", ")}`}
      >
        {total > 0
          ? series.map((item) =>
              counts[item.key] ? (
                <span
                  key={item.key}
                  className={item.fill}
                  style={{ width: `${((counts[item.key] ?? 0) / total) * 100}%` }}
                  title={`${item.label}: ${counts[item.key]}`}
                />
              ) : null,
            )
          : null}
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5">
        {series.map((item) => (
          <div key={item.key} className="flex items-center justify-between gap-2 text-sm">
            <dt className="flex items-center gap-2 text-slate-400">
              <span className={`size-2 rounded-sm ${item.fill}`} aria-hidden="true" />
              {item.label}
            </dt>
            <dd className="font-mono text-slate-100 tabular-nums" data-testid={`${title}-${item.key}`}>
              {counts[item.key] ?? 0}
            </dd>
          </div>
        ))}
      </dl>

      {footer ? <div className="mt-3 text-xs text-slate-500">{footer}</div> : null}
    </section>
  );
}
