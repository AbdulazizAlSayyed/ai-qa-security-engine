import StatusPill, { type Tone } from "@/components/StatusPill";

export interface ChainHop {
  name: string;
  address: string;
  tone: Tone;
  label: string;
  note?: string;
}

interface ConnectionChainProps {
  hops: ChainHop[];
}

/**
 * Phase 0's whole deliverable, drawn as three hops.
 *
 * Each hop's state is derived from a real /health response, never hard-coded:
 * the browser proves hop 1 by rendering at all, the HTTP response proves
 * hop 2, and the database block inside that response proves hop 3.
 */
export default function ConnectionChain({ hops }: ConnectionChainProps) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
      <h2 className="text-sm font-semibold text-slate-200">Connection chain</h2>
      <p className="mt-1 text-sm text-slate-400">
        React &rarr; FastAPI &rarr; MongoDB, verified on every poll.
      </p>

      <ol className="mt-4 flex flex-col gap-3 lg:flex-row lg:items-stretch">
        {hops.map((hop, index) => (
          <li key={hop.name} className="flex flex-1 items-stretch gap-3">
            <div className="flex-1 rounded-lg border border-slate-800 bg-slate-950/60 p-4">
              <div className="flex items-center justify-between gap-3">
                <span className="font-medium text-slate-100">{hop.name}</span>
                <StatusPill tone={hop.tone}>{hop.label}</StatusPill>
              </div>
              <p className="mt-2 font-mono text-xs break-all text-slate-400">{hop.address}</p>
              {hop.note ? <p className="mt-2 text-xs text-slate-500">{hop.note}</p> : null}
            </div>

            {index < hops.length - 1 ? (
              <div
                aria-hidden="true"
                className="hidden items-center text-slate-600 lg:flex"
              >
                &rarr;
              </div>
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  );
}
