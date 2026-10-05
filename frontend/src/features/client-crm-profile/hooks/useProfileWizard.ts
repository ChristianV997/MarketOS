import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";
import type { SaveClientProfile } from "../contracts/clientProfileDraft.ts";
import { runSave } from "../lib/runSave.ts";
import { buildPayload, payloadKey } from "../lib/toPayload.ts";
import { focusId } from "../lib/focusTargets.ts";
import { initialWizardState, wizardReducer, wizardValidation, type WizardState } from "../lib/wizardState.ts";
import { ERROR_SUMMARY_ID, STEP_HEADING_ID } from "../components/StepChrome.tsx";

export function useProfileWizard(onSave: SaveClientProfile | undefined, initial?: Partial<WizardState>) {
  const [state, dispatch] = useReducer(wizardReducer, initial, (seed) => initialWizardState(seed));
  const validation = useMemo(() => wizardValidation(state), [state.draft, state.pending]);
  const saving = useRef(false);

  // Move focus where the last action asked (step heading, error summary, or a field).
  useEffect(() => {
    const request = state.focus;
    if (!request) return;
    const id = request.target === "heading" ? STEP_HEADING_ID : request.target === "summary" ? ERROR_SUMMARY_ID : focusId(request.path ?? "");
    (document.getElementById(id) ?? document.getElementById(STEP_HEADING_ID))?.focus();
  }, [state.focus]);

  const errorFor = useCallback(
    (path: string): string | null => {
      const error = validation.errors.find((item) => item.path === path);
      if (!error) return null;
      return state.attempted.includes(error.step) || state.touched.includes(path) ? error.message : null;
    },
    [validation, state.attempted, state.touched],
  );

  const confirm = useCallback(async () => {
    if (saving.current) return;
    const payload = validation.complete ? buildPayload(state.draft) : null;
    if (payload === null) {
      dispatch({ type: "confirmAttempt" });
      return;
    }
    if (!onSave) {
      dispatch({ type: "demoReviewed", key: payloadKey(payload) ?? "" });
      return;
    }
    saving.current = true;
    try {
      await runSave(onSave, payload, dispatch);
    } finally {
      saving.current = false;
    }
  }, [state.draft, validation.complete, onSave]);

  return { state, dispatch, validation, errorFor, confirm, persistenceAvailable: typeof onSave === "function" };
}
