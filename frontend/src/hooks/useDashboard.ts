import { useCallback, useEffect, useRef, useState } from "react";

import { getDashboard } from "@/services/dashboard";
import type { Dashboard } from "@/types/dashboard";

export interface UseDashboardResult {
  /** null until the first load finishes or fails. */
  dashboard: Dashboard | null;
  error: string | null;
  isLoading: boolean;
  refresh: () => Promise<void>;
}

/**
 * Load the dashboard aggregate. No cache: every refresh re-reads MongoDB.
 *
 * With ``pollMs`` set (only while an assessment started here is running) the
 * aggregate is re-read quietly, the same way the Assessments page follows a
 * run - the state shown is the persisted one, never an estimate.
 */
export function useDashboard(trendDays: number, pollMs: number | null = null): UseDashboardResult {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const inFlight = useRef<AbortController | null>(null);

  const load = useCallback(
    async (quiet: boolean) => {
      inFlight.current?.abort();
      const controller = new AbortController();
      inFlight.current = controller;
      if (!quiet) setIsLoading(true);
      try {
        const loaded = await getDashboard({ historyLimit: 20, trendDays }, controller.signal);
        if (controller.signal.aborted) return;
        setDashboard(loaded);
        setError(null);
      } catch (caught) {
        if (controller.signal.aborted) return;
        setError(caught instanceof Error ? caught.message : "Unexpected error");
      } finally {
        if (!controller.signal.aborted && !quiet) setIsLoading(false);
      }
    },
    [trendDays],
  );

  const refresh = useCallback(() => load(false), [load]);

  useEffect(() => {
    void load(false);
    return () => inFlight.current?.abort();
  }, [load]);

  useEffect(() => {
    if (!pollMs) return;
    const timer = window.setInterval(() => void load(true), pollMs);
    return () => window.clearInterval(timer);
  }, [load, pollMs]);

  return { dashboard, error, isLoading, refresh };
}
