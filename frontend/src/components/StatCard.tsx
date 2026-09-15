import type { ReactNode } from "react";

import type { Tone } from "@/components/StatusPill";

const accent: Record<Tone, string> = {
  positive: "text-emerald-300",
  negative: "text-rose-300",
  warning: "text-amber-300",
  neutral: "text-slate-100",
};

interface StatCardProps {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: Tone;
}

export default function StatCard({ label, value, detail, tone = "neutral" }: StatCardProps) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
      <p className="text-xs font-medium tracking-wide text-slate-400 uppercase">{label}</p>
      <p className={`mt-2 text-2xl font-semibold ${accent[tone]}`}>{value}</p>
      {detail ? <p className="mt-1 text-sm text-slate-400">{detail}</p> : null}
    </div>
  );
}
