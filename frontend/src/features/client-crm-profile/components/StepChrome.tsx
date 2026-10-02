import type { Dispatch, ReactNode } from "react";
import { STEP_IDS, STEP_META, type StepId } from "../contracts/clientProfileDraft.ts";
import { stepStatus, type StepStatus, type WizardAction, type WizardState } from "../lib/wizardState.ts";
import { focusId } from "../lib/focusTargets.ts";
import { stepOfPath, type FieldError, type ProfileValidation } from "../lib/validateProfile.ts";
import { BUTTON_PRIMARY, BUTTON_SECONDARY, WRAP } from "./Fields.tsx";

export interface StepProps {
  state: WizardState;
  validation: ProfileValidation;
  dispatch: Dispatch<WizardAction>;
  /** Message to show for a path, or null. Errors appear after "Next" or after leaving the field. */
  errorFor: (path: string) => string | null;
}

export const STEP_HEADING_ID = "cp-step-heading";
export const ERROR_SUMMARY_ID = "cp-error-summary";

const STATUS_TEXT: Record<StepStatus, string> = {
  complete: "Complete",
  needs_attention: "Needs attention",
  incomplete: "Not complete",
  optional: "Optional, none added",
};

const STATUS_STYLE: Record<StepStatus, string> = {
  complete: "text-emerald-300",
  needs_attention: "text-red-300",
  incomplete: "text-zinc-300",
  optional: "text-zinc-300",
};

export function StepNav({ state, validation, dispatch }: Omit<StepProps, "errorFor">) {
  return (
    <nav aria-label="Profile sections">
      <ol className="flex flex-wrap gap-2 lg:flex-col">
        {STEP_IDS.map((id, index) => {
          const status = stepStatus(id, validation, state);
          const problems = validation.byStep[id].length;
          const current = id === state.step;
          const statusText = status === "needs_attention" || (status === "incomplete" && problems > 0 && id !== "review")
            ? `${STATUS_TEXT[status]}${status === "needs_attention" ? ` (${problems})` : ""}`
            : STATUS_TEXT[status];
          return (
            <li key={id} className="min-w-0">
              <button
                type="button"
                data-step={id}
                data-step-status={status}
                aria-current={current ? "step" : undefined}
                aria-label={`Step ${index + 1} of ${STEP_IDS.length}: ${STEP_META[id].short}. ${statusText}.`}
                onClick={() => dispatch({ type: "goto", step: id })}
                className={`flex min-h-[44px] w-full items-center gap-2 rounded border px-3 py-2 text-left text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-400 ${
                  current ? "border-sky-400 bg-sky-500/10 font-semibold text-zinc-50" : "border-zinc-700 bg-zinc-900/60 text-zinc-200 hover:border-zinc-500"
                }`}
              >
                <span aria-hidden="true" className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-zinc-500 text-xs">
                  {index + 1}
                </span>
                <span aria-hidden="true" className={`text-xs font-semibold sm:hidden ${STATUS_STYLE[status]}`}>
                  {status === "complete" ? "✓" : status === "needs_attention" ? "!" : ""}
                </span>
                <span aria-hidden="true" className="hidden min-w-0 sm:block">
                  <span className="block font-medium">{STEP_META[id].short}</span>
                  <span className={`block text-xs ${STATUS_STYLE[status]}`}>{statusText}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export function StepHeading({ step, children }: { step: StepId; children?: ReactNode }) {
  const index = STEP_IDS.indexOf(step) + 1;
  return (
    <header className="space-y-1">
      <p className="text-xs uppercase tracking-wide text-zinc-400">Step {index} of {STEP_IDS.length}</p>
      <h2 id={STEP_HEADING_ID} tabIndex={-1} className="text-lg font-semibold text-zinc-50 focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400">
        {STEP_META[step].title}
      </h2>
      {children ? <div className="text-sm text-zinc-300">{children}</div> : null}
    </header>
  );
}

/** Lists every problem on the step with a link that moves focus to the field. */
export function ErrorSummary({ step, errors, dispatch }: { step: StepId; errors: readonly FieldError[]; dispatch: Dispatch<WizardAction> }) {
  if (errors.length === 0) return null;
  return (
    <section
      id={ERROR_SUMMARY_ID}
      aria-labelledby="cp-error-summary-heading"
      tabIndex={-1}
      data-error-summary
      className="rounded-lg border border-red-500/60 bg-red-500/10 p-3 text-sm text-red-100 focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-red-300"
    >
      <h2 id="cp-error-summary-heading" className="font-semibold">
        There {errors.length === 1 ? "is 1 problem" : `are ${errors.length} problems`} to fix
      </h2>
      <ul className="mt-1 list-disc space-y-1 pl-5">
        {errors.map((error, index) => (
          <li key={`${error.path}-${index}`} className={WRAP}>
            <a
              href={`#${focusId(error.path)}`}
              className="underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-red-300"
              onClick={(event) => {
                event.preventDefault();
                dispatch({ type: "goto", step: stepOfPath(error.path) === "review" ? step : stepOfPath(error.path), path: error.path });
              }}
            >
              {error.message}
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Buttons shared by steps 1-4. Enter inside a field also triggers "Next" through the form submit. */
export function StepButtons({ state, dispatch }: { state: WizardState; dispatch: Dispatch<WizardAction> }) {
  const index = STEP_IDS.indexOf(state.step);
  return (
    <div className="flex flex-col gap-2 border-t border-zinc-800 pt-4 sm:flex-row sm:justify-between">
      <button type="button" className={BUTTON_SECONDARY} disabled={index === 0} onClick={() => dispatch({ type: "back" })}>
        Back
      </button>
      <button type="submit" className={BUTTON_PRIMARY}>
        Next: {STEP_META[STEP_IDS[index + 1]].short}
      </button>
    </div>
  );
}
