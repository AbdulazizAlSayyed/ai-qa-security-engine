import { Link, useLocation } from "react-router-dom";

export default function NotFoundPage() {
  const { pathname } = useLocation();

  return (
    <div className="mx-auto max-w-lg py-16 text-center">
      <p className="font-mono text-sm text-slate-500">404</p>
      <h1 className="mt-2 text-2xl font-semibold text-slate-100">No such page</h1>
      <p className="mt-2 text-sm text-slate-400">
        <span className="font-mono">{pathname}</span> does not exist yet. Most of the console
        arrives with later phases.
      </p>
      <Link
        to="/"
        className="mt-6 inline-block rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-200 transition-colors hover:border-slate-500 hover:bg-slate-800/60"
      >
        Back to the dashboard
      </Link>
    </div>
  );
}
