import StatCard from "@/components/StatCard";
import { NAVIGATION_LABELS } from "@/types/discovery";
import type { ApplicationMap, DiscoveredPage } from "@/types/discovery";

interface Props {
  map: ApplicationMap;
  onOpenPage: (page: DiscoveredPage) => void;
}

function when(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

/**
 * One application map: what the crawl found, and what it could not.
 *
 * Every number here comes from the run that is being displayed. Nothing is
 * assumed about a target, and a failed run shows its reason rather than an
 * empty map that looks like an application with no pages.
 */
export default function ApplicationMapView({ map, onOpenPage }: Props) {
  const failed = map.status === "failed";

  return (
    <div className="flex flex-col gap-6">
      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div>
            <p className="text-sm text-slate-300">
              <span className="font-mono text-xs text-sky-300">
                {map.discovery_id.slice(0, 12)}
              </span>{" "}
              · {map.base_url}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {when(map.started_at)} · {(map.duration_ms / 1000).toFixed(1)}s ·{" "}
              {String(map.metadata.browser ?? "chromium")}{" "}
              {String(map.metadata.browser_version ?? "")}
            </p>
          </div>
          <span
            className={`rounded-full border px-3 py-1 text-xs ${
              failed
                ? "border-rose-500/50 text-rose-300"
                : "border-emerald-500/50 text-emerald-300"
            }`}
          >
            {map.status}
          </span>
        </div>

        <p className="mt-3 text-sm text-slate-400">
          {map.authentication.state === "authenticated" ? (
            <>
              Explored as <span className="text-slate-200">{map.authentication.account_name}</span>{" "}
              via {map.authentication.mode}.
            </>
          ) : (
            <>Explored anonymously. {map.authentication.reason}</>
          )}
        </p>

        {map.error ? (
          <p className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-sm text-rose-200">
            {map.error}
          </p>
        ) : null}

        {map.notes.length > 0 ? (
          <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-slate-400">
            {map.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        ) : null}
      </section>

      <section className="grid gap-4 sm:grid-cols-3 lg:grid-cols-6">
        <StatCard label="Pages" value={map.summary.pages} />
        <StatCard label="Routes" value={map.summary.routes} />
        <StatCard label="Links" value={map.summary.links} />
        <StatCard label="Forms" value={map.summary.forms} />
        <StatCard label="Elements" value={map.summary.elements} />
        <StatCard
          label="Blocked"
          value={map.summary.blocked}
          tone={map.summary.blocked > 0 ? "negative" : "neutral"}
        />
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold text-slate-200">
          Pages ({map.pages.length})
        </h3>
        {map.pages.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-800 bg-slate-900/40 p-8 text-center text-sm text-slate-400">
            No page could be read. The reason is above.
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-slate-800">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-900 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-2">Path</th>
                  <th className="px-3 py-2">Route</th>
                  <th className="px-3 py-2">Reached by</th>
                  <th className="px-3 py-2 text-right">Depth</th>
                  <th className="px-3 py-2 text-right">Links</th>
                  <th className="px-3 py-2 text-right">Forms</th>
                  <th className="px-3 py-2 text-right">Elements</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {map.pages.map((page) => (
                  <tr
                    key={page.url}
                    onClick={() => onOpenPage(page)}
                    className="cursor-pointer bg-slate-900/60 transition-colors hover:bg-slate-800/50"
                  >
                    <td className="max-w-72 truncate px-3 py-2 font-mono text-xs text-slate-100">
                      {page.path}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-slate-400">
                      {page.route_template}
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-400">
                      {NAVIGATION_LABELS[page.navigation_kind]}
                    </td>
                    <td className="px-3 py-2 text-right text-slate-300">{page.depth}</td>
                    <td className="px-3 py-2 text-right text-slate-300">{page.link_count}</td>
                    <td className="px-3 py-2 text-right text-slate-300">{page.form_count}</td>
                    <td className="px-3 py-2 text-right text-slate-300">
                      {page.element_count}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {map.redirects.length > 0 ? (
        <section>
          <h3 className="mb-2 text-sm font-semibold text-slate-200">
            Redirects ({map.redirects.length})
          </h3>
          <ul className="divide-y divide-slate-800 overflow-hidden rounded-xl border border-slate-800">
            {map.redirects.map((redirect, index) => (
              <li
                key={`${redirect.requested_url}-${index}`}
                className="flex flex-wrap items-center gap-2 bg-slate-900/60 px-3 py-2 text-sm"
              >
                <span className="font-mono text-xs text-slate-200">
                  {redirect.requested_path}
                </span>
                <span className="text-slate-500">→</span>
                <span className="font-mono text-xs text-slate-200">{redirect.final_path}</span>
                {redirect.authentication_required ? (
                  <span
                    className="rounded-full border border-amber-500/50 px-2 py-0.5 text-xs text-amber-300"
                    title="Observed: anonymous access landed on a page asking for a password"
                  >
                    sign-in required
                  </span>
                ) : null}
                {redirect.status ? (
                  <span className="text-xs text-slate-500">HTTP {redirect.status}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {map.blocked.length > 0 ? (
        <section>
          <h3 className="mb-2 text-sm font-semibold text-slate-200">
            Blocked ({map.blocked.length})
          </h3>
          <ul className="divide-y divide-slate-800 overflow-hidden rounded-xl border border-slate-800">
            {map.blocked.map((item, index) => (
              <li key={`${item.url}-${index}`} className="bg-slate-900/60 px-3 py-2">
                <p className="font-mono text-xs text-slate-200">{item.path}</p>
                <p className="mt-0.5 text-xs text-rose-200/70">{item.reason}</p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {map.summary.external_links > 0 ? (
        <p className="text-xs text-slate-500">
          {map.summary.external_links} link(s) point outside {map.base_url}. They are
          recorded and were never visited.
        </p>
      ) : null}
    </div>
  );
}
