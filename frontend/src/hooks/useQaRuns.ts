import { useCallback, useEffect, useRef, useState } from "react";

import { listQaRuns } from "@/services/qa";
import type { QaRun } from "@/types/qa";

export interface UseQaRunsResult {
  /** null until the first load finishes or fails. */
  runs: QaRun[] | null;
  error: string | null;
  isLoading: boolean;
  refresh: () => Promise<void>;
}

/**
 * Load QA run history from the backend.
 *
 * No local cache: after starting a run the page calls refresh(), so what is
 * shown is always what MongoDB holds.
 */
export function useQaRuns(limit = 50): UseQaRunsResult {
  const [runs, setRuns] = useState<QaRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const inFlight = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;

    setIsLoading(true);
    try {
      const loaded = await listQaRuns(limit, controller.signal);
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
