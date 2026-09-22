import type { SeriesDef } from "@/components/dashboard/series";
import type { TrendPoint } from "@/types/dashboard";

interface TrendChartProps<K extends string> {
  title: string;
  description: string;
  points: TrendPoint[];
  series: SeriesDef<K>[];
  value: (point: TrendPoint, key: K) => number;
}

/**
 * Stacked columns, one per UTC day that has an assessment. Days without an
 * assessment are not drawn - there is no data for them, so none is invented.
 * Plain elements, no charting dependency.
 */
export default function TrendChart<K extends string>({
  title,
  description,
  points,
  series,
  value,
}: TrendChartProps<K>) {
  const totals = points.map((point) => series.reduce((sum, s) => sum + value(point, s.key), 0));
  const max = Math.max(0, ...totals);
  const labelEvery = points.length > 14 ? Math.ceil(points.length / 14) : 1;

  return (
    <figure className="rounded-xl border border-slate-800 bg-slate-950/40 p-4" aria-label={title}>
      <figcaption>
        <p className="text-sm font-medium text-slate-200">{title}</p>
        <p className="text-xs text-slate-500">{description}</p>
      </figcaption>

      <div className="mt-3 flex gap-2">
        <div className="flex h-32 flex-col justify-between text-right font-mono text-[10px] text-slate-600 tabular-nums">
          <span>{max}</span>
          <span>0</span>
        </div>
        <div className="min-w-0 flex-1 overflow-x-auto">
          <div className="flex h-32 items-end gap-1 border-b border-l border-slate-800 px-1">
            {points.map((point, index) => {
              const total = totals[index] ?? 0;
              const breakdown = series.map((s) => `${s.label} ${value(point, s.key)}`).join(", ");
              return (
                <div
                  key={point.date}
                  className="flex h-full max-w-12 min-w-3 flex-1 flex-col-reverse"
                  title={`${point.date}: ${total} (${breakdown})`}
                  role="img"
                  aria-label={`${point.date}: ${breakdown}`}
                >
                  {max > 0
                    ? series.map((s) => {
                        const v = value(point, s.key);
                        return v > 0 ? (
                          <span
                            key={s.key}
                            className={`block w-full ${s.fill} first:rounded-b-none last:rounded-t-sm`}
                            style={{ height: `${(v / max) * 100}%` }}
                          />
                        ) : null;
                      })
                    : null}
                </div>
              );
            })}
          </div>
          <div className="flex gap-1 px-1 pt-1">
            {points.map((point, index) => (
              <span
                key={point.date}
                className="max-w-12 min-w-3 flex-1 text-center font-mono text-[10px] whitespace-nowrap text-slate-600"
              >
                {index % labelEvery === 0 ? point.date.slice(5) : ""}
              </span>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
        {series.map((s) => (
          <span key={s.key} className="flex items-center gap-1.5 text-[11px] text-slate-400">
            <span className={`size-2 rounded-sm ${s.fill}`} aria-hidden="true" />
            {s.label}
          </span>
        ))}
        {max === 0 ? (
          <span className="text-[11px] text-slate-500">All zero in this period.</span>
        ) : null}
      </div>
    </figure>
  );
}
