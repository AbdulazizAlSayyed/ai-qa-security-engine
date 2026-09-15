import type { ReactNode } from "react";

export type Tone = "positive" | "negative" | "warning" | "neutral";

const pillTone: Record<Tone, string> = {
  positive: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30",
  negative: "bg-rose-500/10 text-rose-300 ring-rose-500/30",
  warning: "bg-amber-500/10 text-amber-300 ring-amber-500/30",
  neutral: "bg-slate-500/10 text-slate-300 ring-slate-500/30",
};

const dotTone: Record<Tone, string> = {
  positive: "bg-emerald-400",
  negative: "bg-rose-400",
  warning: "bg-amber-400",
  neutral: "bg-slate-400",
};

interface StatusPillProps {
  tone: Tone;
  children: ReactNode;
  pulse?: boolean;
}

export default function StatusPill({ tone, children, pulse = false }: StatusPillProps) {
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset ${pillTone[tone]}`}
    >
      <span
        className={`size-1.5 shrink-0 rounded-full ${dotTone[tone]} ${pulse ? "animate-pulse" : ""}`}
      />
      {children}
    </span>
  );
}
