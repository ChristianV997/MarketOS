import { useCallback, useEffect, useReducer, useRef } from "react";
import type { FetchLike } from "../lib/clientProfileApi.ts";
import { INITIAL_SESSION, makeSave, runLoad, sessionReducer, type ProfileSession } from "../lib/profileSession.ts";

/**
 * Loads the signed-in client's profile once (GET) and exposes `save`, which sends
 * POST while no profile exists and PATCH after. All identity is server-side: this
 * hook keeps no workspace or tenant value and passes none.
 */
export function useProfileSession(enabled: boolean, fetchImpl?: FetchLike, initial?: ProfileSession) {
  const [session, dispatch] = useReducer(sessionReducer, initial ?? INITIAL_SESSION);
  const [attempt, retry] = useReducer((count: number) => count + 1, 0);
  const sessionRef = useRef(session);
  sessionRef.current = session;

  useEffect(() => {
    if (!enabled || initial) return;
    const controller = new AbortController();
    void runLoad({ fetchImpl, signal: controller.signal }, dispatch);
    return () => controller.abort();
  }, [enabled, attempt, fetchImpl, initial]);

  const save = useCallback(makeSave(() => sessionRef.current, dispatch, { fetchImpl }), [fetchImpl]);

  return { session, save, retry };
}
