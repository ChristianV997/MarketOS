import { useEffect, useRef } from "react";
import type { ProfileErrorCode } from "../contracts/clientProfileDraft.ts";
import { LOAD_ERROR_TEXT } from "../lib/errorCopy.ts";
import { BUTTON_PRIMARY } from "./Fields.tsx";

const FRAME = "mx-auto w-full max-w-5xl min-w-0 space-y-4 p-3 text-zinc-100 sm:p-6";

/** The h1 takes focus on mount: a retry unmounts the button that was pressed, so focus would otherwise fall to <body>. */
function Header() {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, []);
  return (
    <header className="space-y-2">
      <p className="inline-flex rounded border border-zinc-600 bg-zinc-900 px-2 py-0.5 text-xs text-zinc-200">Client view</p>
      <h1 ref={heading} id="cp-page-heading" tabIndex={-1} className="text-xl font-semibold text-zinc-50 focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400">Company profile</h1>
    </header>
  );
}

export function LoadingPanel() {
  return (
    <section aria-labelledby="cp-page-heading" data-client-profile data-load-phase="loading" className={FRAME}>
      <Header />
      <div role="status" aria-live="polite" aria-busy="true" data-load-status className="rounded-lg border border-zinc-700 bg-zinc-900/60 p-3 text-sm text-zinc-200">
        Loading your saved profile…
      </div>
    </section>
  );
}

/** Load failed: the form is not shown because the page cannot tell whether a profile exists. */
export function LoadFailedPanel({ code, onRetry }: { code: ProfileErrorCode; onRetry: () => void }) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, [code]);
  return (
    <section aria-labelledby="cp-page-heading" data-client-profile data-load-phase="failed" data-load-error={code} className={FRAME}>
      <Header />
      <div role="alert" className="space-y-2 rounded-lg border border-red-500/60 bg-red-500/10 p-3 text-sm text-red-100">
        <h2 ref={heading} tabIndex={-1} className="font-semibold focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-red-300">
          Your saved profile could not be loaded
        </h2>
        <p>{LOAD_ERROR_TEXT[code]}</p>
        <p>Nothing was changed. No profile information is shown until it loads.</p>
        <button type="button" className={BUTTON_PRIMARY} onClick={onRetry}>
          Try again
        </button>
      </div>
    </section>
  );
}

/** First visit: the server has no profile for this account yet (GET 404). */
export function NoSavedProfileNote() {
  return (
    <div className="mx-auto w-full max-w-5xl px-3 pt-3 sm:px-6 sm:pt-6">
      <p role="note" data-no-saved-profile className="rounded-lg border border-zinc-600 bg-zinc-900/60 px-3 py-2 text-sm text-zinc-200">
        No saved profile was found for this account. Fill in the steps and confirm on the last step to create one.
      </p>
    </div>
  );
}

/** A saved profile was loaded: say which fields the service holds and which the form starts empty. */
export function LoadedProfileNote() {
  return (
    <div className="mx-auto w-full max-w-5xl px-3 pt-3 sm:px-6 sm:pt-6">
      <p role="note" data-loaded-profile className="rounded-lg border border-zinc-600 bg-zinc-900/60 px-3 py-2 text-sm text-zinc-200">
        Your saved profile was loaded. The service keeps only your company name, business type, segments, target markets, offering names and
        social handles, so details such as categories, offering descriptions and links start empty here.
      </p>
    </div>
  );
}
