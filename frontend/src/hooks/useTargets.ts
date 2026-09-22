import { useCallback, useEffect, useRef, useState } from "react";

import { listTargets } from "@/services/targets";
import type { Target } from "@/types/target";

export interface UseTargetsResult {
  /** null until the first load finishes or fails. */
  targets: Target[] | null;
  error: string | null;
  isLoading: boolean;
  refresh: () => Promise<void>;
}

/**
 * Load the target registry from the backend.
 *
 * There is no local cache and no optimistic state: after any mutation the
 * page calls refresh(), so what the user sees is always what MongoDB
 * actually holds.
 */
export function useTargets(): UseTargetsResult {
  const [targets, setTargets] = useState<Target[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const inFlight = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;

    setIsLoading(true);
    try {
      const loaded = await listTargets(controller.signal);
      if (controller.signal.aborted) return;
      setTargets(loaded);
      setError(null);
    } catch (caught) {
      if (controller.signal.aborted) return;
      setTargets(null);
      setError(caught instanceof Error ? caught.message : "Unexpected error");
    } finally {
      if (!controller.signal.aborted) setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    return () => inFlight.current?.abort();
  }, [refresh]);

  return { targets, error, isLoading, refresh };
}
