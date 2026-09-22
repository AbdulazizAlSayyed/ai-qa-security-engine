import { useCallback, useEffect, useRef, useState } from "react";

import { listAssessments } from "@/services/assessments";
import type { Assessment } from "@/types/assessment";

export interface UseAssessmentsResult {
  assessments: Assessment[] | null;
  error: string | null;
  isLoading: boolean;
  refresh: () => Promise<void>;
}

/**
 * Load assessment history. No local cache; every refresh re-reads MongoDB.
 *
 * With ``pollMs`` set, the list is re-read quietly on that interval. The
 * orchestrator persists every state transition, so this shows the real
 * current state of a running assessment - never an estimate.
 */
export function useAssessments(limit = 25, pollMs: number | null = null): UseAssessmentsResult {
  const [assessments, setAssessments] = useState<Assessment[] | null>(null);
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
        const loaded = await listAssessments(limit, controller.signal);
        if (controller.signal.aborted) return;
        setAssessments(loaded);
        setError(null);
      } catch (caught) {
        if (controller.signal.aborted) return;
        if (!quiet) setAssessments(null);
        setError(caught instanceof Error ? caught.message : "Unexpected error");
      } finally {
        if (!controller.signal.aborted && !quiet) setIsLoading(false);
      }
    },
    [limit],
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

  return { assessments, error, isLoading, refresh };
}
