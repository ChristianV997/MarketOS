import { LoadedProfileNote, LoadFailedPanel, LoadingPanel, NoSavedProfileNote } from "./components/LoadPanels.tsx";
import ClientProfileWizard from "./ClientProfileWizard.tsx";
import { useProfileSession } from "./hooks/useProfileSession.ts";
import type { AccessTokenProvider, FetchLike } from "./lib/clientProfileApi.ts";
import type { ProfileSession } from "./lib/profileSession.ts";
import type { WizardState } from "./lib/wizardState.ts";

export interface ClientProfileOnboardingProps {
  /**
   * Supplies the signed-in caller's bearer token for the profile service. Only
   * the code that mounts this page can provide it (never a URL parameter, a stored
   * value or something the person types). When absent the page is the offline
   * demo: no request is made and nothing is saved. The mounted routes pass none,
   * because nothing in this repository issues those tokens yet.
   */
  getAccessToken?: AccessTokenProvider;
  /** Test seam: replace `fetch`. */
  fetchImpl?: FetchLike;
  /** Test seam: render a given session instead of loading. */
  initialSession?: ProfileSession;
  /** Test seam: start the wizard from a given state. */
  initialState?: Partial<WizardState>;
}

/**
 * Client CRM onboarding page. Separate from the owner dashboard; it renders no
 * owner navigation. The host layout (ClientShell) supplies the <main> landmark.
 */
export default function ClientProfileOnboardingPage({ getAccessToken, fetchImpl, initialSession, initialState }: ClientProfileOnboardingProps) {
  const live = typeof getAccessToken === "function";
  const { session, save, retry } = useProfileSession(live, getAccessToken, fetchImpl, initialSession);

  if (!live && !initialSession) return <ClientProfileWizard initialState={initialState} />;
  if (session.phase === "loading") return <LoadingPanel />;
  if (session.phase === "load_failed") return <LoadFailedPanel code={session.code} onRetry={retry} />;

  return (
    <>
      {session.mode === "create" ? <NoSavedProfileNote /> : <LoadedProfileNote />}
      {/* Remounts only when a (re)load completes; the form's own saves and edits never reset it. */}
      <ClientProfileWizard key={session.version} onSave={save} focusOnMount initialState={{ draft: session.draft, ...initialState }} />
    </>
  );
}
