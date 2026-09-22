/**
 * Colour and label for every series the dashboard draws. The vocabularies are
 * the ones the backend already uses; hues match SeverityBadge / PriorityBadge.
 */

export interface SeriesDef<K extends string> {
  key: K;
  label: string;
  /** Solid fill for bars and legend swatches. */
  fill: string;
}

export const SEVERITY_SERIES: SeriesDef<"high" | "medium" | "low" | "informational">[] = [
  { key: "high", label: "High", fill: "bg-rose-400" },
  { key: "medium", label: "Medium", fill: "bg-amber-400" },
  { key: "low", label: "Low", fill: "bg-sky-400" },
  { key: "informational", label: "Info", fill: "bg-slate-500" },
];

export const PRIORITY_SERIES: SeriesDef<"P1" | "P2" | "P3" | "P4">[] = [
  { key: "P1", label: "P1", fill: "bg-rose-400" },
  { key: "P2", label: "P2", fill: "bg-orange-400" },
  { key: "P3", label: "P3", fill: "bg-sky-400" },
  { key: "P4", label: "P4", fill: "bg-slate-500" },
];

export const QA_SERIES: SeriesDef<"passed" | "failed" | "skipped" | "error">[] = [
  { key: "passed", label: "Passed", fill: "bg-emerald-400" },
  { key: "failed", label: "Failed", fill: "bg-rose-400" },
  { key: "skipped", label: "Skipped", fill: "bg-slate-500" },
  { key: "error", label: "Error", fill: "bg-amber-400" },
];
