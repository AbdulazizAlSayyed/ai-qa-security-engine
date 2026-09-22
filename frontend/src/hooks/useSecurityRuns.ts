import { useCallback, useEffect, useRef, useState } from "react";

import { listSecurityRuns } from "@/services/security";
import type { SecurityRun } from "@/types/security";

export interface UseSecurityRunsResult {
  /** null until the first load finishes or fails. */
  runs: SecurityRun[] | null;
  error: string | null;
  isLoading: boolean;
  refresh: () => Promise<void>;
}

/** Load security run history. No local cache; refresh() re-reads MongoDB. */
export function useSecurityRuns(limit = 50): UseSecurityRunsResult {
  const [runs, setRuns] = useState<SecurityRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const inFlight = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;

    setIsLoading(true);
    try {
      const loaded = await listSecurityRuns(limit, controller.signal);
      if (controller.signal.aborted) return;
      setRuns(loaded);
      setError(null);
    } catch (caught) {
      if (controller.signal.aborted) return;
      setRuns(null);
      setError(caught instanceof Error ? caught.message : "Unexpected error");
    } finally {
      if (!controller.signal.aborted) setIsLoading(false);
    }
  }, [limit]);

  useEffect(() => {
    void refresh();
    return () => inFlight.current?.abort();
  }, [refresh]);

  return { runs, error, isLoading, refresh };
}
