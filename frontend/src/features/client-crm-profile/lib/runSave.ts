import { ProfileSaveError, type ClientProfileDraftPayload, type SaveClientProfile } from "../contracts/clientProfileDraft.ts";
import { payloadKey } from "./toPayload.ts";
import type { WizardAction } from "./wizardState.ts";

/**
 * Runs the injected persistence function and reports the outcome as reducer
 * actions. "saved" is only dispatched after the promise resolves, and a failure
 * is reduced to a short code: raw error text (which may echo server internals or
 * submitted values) is never surfaced.
 */
export async function runSave(
  save: SaveClientProfile,
  payload: ClientProfileDraftPayload,
  dispatch: (action: WizardAction) => void,
): Promise<void> {
  dispatch({ type: "saveStarted" });
  try {
    await save(payload);
  } catch (error) {
    dispatch({ type: "saveFailed", code: error instanceof ProfileSaveError ? error.code : "unknown" });
    return;
  }
  dispatch({ type: "saveSucceeded", key: payloadKey(payload) ?? "" });
}
