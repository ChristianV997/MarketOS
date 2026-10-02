import { useCallback, useEffect, useReducer, useRef } from "react";
import type { AccessTokenProvider, FetchLike } from "../lib/clientProfileApi.ts";
import { INITIAL_SESSION, makeSave, runLoad, sessionReducer, type ProfileSession } from "../lib/profileSession.ts";

/**
 * Loads the signed-in client's profile once (GET) and exposes `save`, which sends
 * POST while no profile exists and PATCH after. All identity is server-side: this
 * hook keeps no workspace, tenant or token value; it only passes the token
 * provider through so the API client can read a token per request.
 */
export function useProfileSession(enabled: boolean, getAccessToken?: AccessTokenProvider, fetchImpl?: FetchLike, initial?: ProfileSession) {
  const [session, dispatch] = useReducer(sessionReducer, initial ?? INITIAL_SESSION);
  const [attempt, retry] = useReducer((count: number) => count + 1, 0);
  const sessionRef = useRef(session);
  sessionRef.current = session;
  // A host may pass an inline function; reading it through a ref keeps the load effect from re-running on every render.
  const providerRef = useRef(getAccessToken);
  providerRef.current = getAccessToken;
  const tokenProvider = useCallback<AccessTokenProvider>(async () => (providerRef.current ? providerRef.current() : null), []);

  useEffect(() => {
    if (!enabled || initial) return;
    const controller = new AbortController();
    void runLoad({ getAccessToken: tokenProvider, fetchImpl, signal: controller.signal }, dispatch);
    return () => controller.abort();
  }, [enabled, attempt, tokenProvider, fetchImpl, initial]);

  const save = useCallback(makeSave(() => sessionRef.current, dispatch, { getAccessToken: tokenProvider, fetchImpl }), [tokenProvider, fetchImpl]);

  return { session, save, retry };
}
