import type { ProfileDraft, ProfileErrorCode } from "../contracts/clientProfileDraft.ts";
import { EMPTY_DRAFT } from "./wizardState.ts";
import type { ClientProfileDraftPayload } from "../contracts/clientProfileDraft.ts";
import { fetchClientProfile, saveClientProfile, type ClientProfileApiOptions, type SaveMode } from "./clientProfileApi.ts";

/**
 * What the container knows about the server-side profile. It holds no identity:
 * only whether a saved profile exists (so the next save is POST or PATCH) and the
 * draft to start the form from.
 */
export type ProfileSession = { version: number } & (
  | { phase: "loading" }
  | { phase: "ready"; mode: SaveMode; draft: ProfileDraft }
  | { phase: "load_failed"; code: ProfileErrorCode }
);

export type SessionAction =
  | { type: "loadStarted" }
  | { type: "loadedExisting"; draft: ProfileDraft }
  | { type: "loadedNone" }
  | { type: "loadFailed"; code: ProfileErrorCode }
  | { type: "saved" };

/** `version` counts completed loads so the form remounts for a newly loaded profile but not after its own saves. */
export const INITIAL_SESSION: ProfileSession = { version: 0, phase: "loading" };

export function sessionReducer(state: ProfileSession, action: SessionAction): ProfileSession {
  switch (action.type) {
    case "loadStarted": return { version: state.version, phase: "loading" };
    case "loadedExisting": return { version: state.version + 1, phase: "ready", mode: "update", draft: action.draft };
    case "loadedNone": return { version: state.version + 1, phase: "ready", mode: "create", draft: EMPTY_DRAFT };
    case "loadFailed": return { version: state.version, phase: "load_failed", code: action.code };
    // A successful create means the next save must be an update; the form keeps its own draft.
    case "saved": return state.phase === "ready" ? { ...state, mode: "update" } : state;
  }
}

/** GET once and report the outcome as session actions. An aborted request reports nothing. */
export async function runLoad(options: ClientProfileApiOptions, dispatch: (action: SessionAction) => void): Promise<void> {
  dispatch({ type: "loadStarted" });
  const result = await fetchClientProfile(options);
  if (result.kind === "aborted") return;
  if (result.kind === "ok") dispatch({ type: "loadedExisting", draft: result.draft });
  else if (result.kind === "not_found") dispatch({ type: "loadedNone" });
  else dispatch({ type: "loadFailed", code: result.code });
}

/**
 * The save function handed to the wizard: POST while no saved profile exists,
 * PATCH after. `saved` is dispatched only after the server accepted the request,
 * so a failed or unreadable reply leaves the mode (and the "saved" claim) alone.
 */
export function makeSave(
  getSession: () => ProfileSession,
  dispatch: (action: SessionAction) => void,
  options: ClientProfileApiOptions,
): (payload: ClientProfileDraftPayload) => Promise<void> {
  return async (payload) => {
    const current = getSession();
    if (current.phase !== "ready") throw new Error("profile_not_loaded");
    await saveClientProfile(current.mode, payload, options);
    dispatch({ type: "saved" });
  };
}
