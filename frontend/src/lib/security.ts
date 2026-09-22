import type { Tone } from "@/components/StatusPill";
import type {
  ComponentStatus,
  SecurityRunStatus,
  Severity,
} from "@/types/security";

/** Severity colouring. Informational is deliberately muted, not alarming. */
export const SEVERITY_CLASS: Record<Severity, string> = {
  high: "bg-rose-500/10 text-rose-300 ring-rose-500/30",
  medium: "bg-amber-500/10 text-amber-300 ring-amber-500/30",
  low: "bg-sky-500/10 text-sky-300 ring-sky-500/30",
  informational: "bg-slate-500/10 text-slate-300 ring-slate-500/30",
};

export const SEVERITY_LABEL: Record<Severity, string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
  informational: "Info",
};

/**
 * A run with findings is still a success: the engine did its job. Only a
 * scanner that could not finish, or a broken platform, is coloured badly.
 */
export const RUN_STATUS_TONE: Record<SecurityRunStatus, Tone> = {
  completed: "positive",
  failed: "negative",
  error: "warning",
};

export const RUN_STATUS_LABEL: Record<SecurityRunStatus, string> = {
  completed: "Completed",
  failed: "Scanner failed",
  error: "Engine error",
};

export const COMPONENT_TONE: Record<ComponentStatus, Tone> = {
  completed: "positive",
  skipped: "neutral",
  failed: "negative",
};

export const COMPONENT_LABEL: Record<ComponentStatus, string> = {
  completed: "Completed",
  skipped: "Skipped",
  failed: "Failed",
};

export const COMPONENT_TITLE: Record<string, string> = {
  zap: "OWASP ZAP",
  api_probes: "API security probes",
  authorization_probes: "Authorization probes",
  semgrep: "Semgrep (static analysis)",
};

export function componentTitle(name: string): string {
  return COMPONENT_TITLE[name] ?? name;
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

export function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}
