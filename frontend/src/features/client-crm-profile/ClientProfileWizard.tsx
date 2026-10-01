import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import type { SaveClientProfile } from "./contracts/clientProfileDraft.ts";
import { ErrorSummary, StepButtons, StepNav } from "./components/StepChrome.tsx";
import { StepAudience } from "./components/StepAudience.tsx";
import { StepCompany } from "./components/StepCompany.tsx";
import { StepOfferings } from "./components/StepOfferings.tsx";
import { StepReview } from "./components/StepReview.tsx";
import { StepSocial } from "./components/StepSocial.tsx";
import { BUTTON_SECONDARY } from "./components/Fields.tsx";
import { useProfileWizard } from "./hooks/useProfileWizard.ts";
import { isBlank, type WizardState } from "./lib/wizardState.ts";

export interface ClientProfileWizardProps {
  /**
   * Persistence seam. Leave undefined for demo mode (fictional data, nothing is
   * stored or sent). The container passes it only for the live, server-backed
   * profile: the wizard never sees or accepts a workspace or client id, so whose
   * profile this is must be decided server-side from the session.
   */
  onSave?: SaveClientProfile;
  /** Test/preview seam: start from a given wizard state. */
  initialState?: Partial<WizardState>;
}

type ReplaceTarget = "sample" | "clear";

/**
 * Guided company-profile wizard (presentational). It loads nothing and calls no
 * API itself: demo mode when `onSave` is absent, otherwise it saves only through
 * the function it is given. Client-facing and separate from the owner dashboard.
 * The host layout must provide the page's <main> landmark.
 */
export default function ClientProfileWizard({ onSave, initialState }: ClientProfileWizardProps) {
  const { state, dispatch, validation, errorFor, confirm, persistenceAvailable } = useProfileWizard(onSave, initialState);
  const stepProps = { state, validation, dispatch, errorFor };
  const stepErrors = state.attempted.includes(state.step) ? validation.byStep[state.step] : [];

  // Replacing typed work needs an explicit yes; an untouched form is replaced straight away.
  const [replace, setReplace] = useState<ReplaceTarget | null>(null);
  const keepButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (replace) keepButton.current?.focus();
  }, [replace]);
  function requestReplace(target: ReplaceTarget) {
    if (isBlank(state)) dispatch({ type: target === "sample" ? "loadSample" : "clear" });
    else setReplace(target);
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (state.step === "review") void confirm();
    else dispatch({ type: "next" });
  }

  // Enter in a single-line field only advances on the one-field steps; on the list steps it would skip the rest of a row.
  function onKeyDown(event: KeyboardEvent<HTMLFormElement>) {
    const target = event.target as HTMLElement;
    if (event.key === "Enter" && (state.step === "offerings" || state.step === "social") && target.tagName === "INPUT") {
      event.preventDefault();
    }
  }

  return (
    <section aria-labelledby="cp-page-heading" data-client-profile className="mx-auto w-full max-w-5xl min-w-0 space-y-4 p-3 text-zinc-100 sm:p-6">
      <p role="status" aria-live="polite" aria-atomic="true" className="sr-only" data-live-summary>
        {state.announcement}
      </p>

      <header className="space-y-2">
        <p className="inline-flex rounded border border-zinc-600 bg-zinc-900 px-2 py-0.5 text-xs text-zinc-200">Client view</p>
        <h1 id="cp-page-heading" className="text-xl font-semibold text-zinc-50">Company profile</h1>
        <p className="text-sm text-zinc-300">
          Set up your own company profile. This page does not load information about any other company and has no owner controls.
        </p>
      </header>

      {persistenceAvailable ? (
        <div role="note" data-mode="persistent" className="rounded-lg border border-zinc-600 bg-zinc-900/60 p-3 text-sm text-zinc-200">
          Your profile is saved to the server only when you confirm on the last step and the server accepts it.
        </div>
      ) : (
        <div role="note" data-mode="demo" className="space-y-2 rounded-lg border border-violet-400/60 bg-violet-500/10 p-3 text-sm text-violet-100">
          <p className="font-semibold">Demo mode. Nothing is saved or sent.</p>
          <p>Everything here is fictional demo data: it is not observed, not saved and not connected to any account.</p>
          <p>
            No real client information is loaded, and anything you type stays in this browser tab until you leave the page. Saving needs a
            secure, signed-in storage service, which is not connected yet.
          </p>
          {replace ? (
            <div role="group" aria-label="Replace what you typed?" data-replace-confirm className="space-y-2 rounded border border-violet-300/60 p-2">
              <p>{replace === "sample" ? "Filling in sample data replaces what you typed." : "Clearing the form removes what you typed."}</p>
              <div className="flex flex-wrap gap-2">
                <button type="button" ref={keepButton} className={BUTTON_SECONDARY} onClick={() => setReplace(null)}>
                  Keep what I typed
                </button>
                <button
                  type="button"
                  className={BUTTON_SECONDARY}
                  onClick={() => {
                    dispatch({ type: replace === "sample" ? "loadSample" : "clear" });
                    setReplace(null);
                  }}
                >
                  {replace === "sample" ? "Replace with sample data" : "Clear the form"}
                </button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              <button type="button" className={BUTTON_SECONDARY} onClick={() => requestReplace("sample")}>
                Fill with fictional sample data
              </button>
              <button type="button" className={BUTTON_SECONDARY} onClick={() => requestReplace("clear")}>
                Clear the form
              </button>
            </div>
          )}
        </div>
      )}

      <div className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-[14rem_minmax(0,1fr)]">
        <StepNav state={state} validation={validation} dispatch={dispatch} />
        <form
          noValidate
          onSubmit={onSubmit}
          onKeyDown={onKeyDown}
          aria-label="Profile steps"
          className="min-w-0 space-y-5 rounded-lg border border-zinc-800 bg-zinc-900/30 p-3 sm:p-5"
        >
          <ErrorSummary step={state.step} errors={stepErrors} dispatch={dispatch} />
          {state.step === "company" ? <StepCompany {...stepProps} /> : null}
          {state.step === "audience" ? <StepAudience {...stepProps} /> : null}
          {state.step === "offerings" ? <StepOfferings {...stepProps} /> : null}
          {state.step === "social" ? <StepSocial {...stepProps} /> : null}
          {state.step === "review" ? <StepReview {...stepProps} persistenceAvailable={persistenceAvailable} /> : null}
          {state.step !== "review" ? <StepButtons state={state} dispatch={dispatch} /> : null}
        </form>
      </div>
    </section>
  );
}
