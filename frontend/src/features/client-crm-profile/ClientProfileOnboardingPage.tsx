import { LoadFailedPanel, LoadingPanel, NoSavedProfileNote } from "./components/LoadPanels.tsx";
import ClientProfileWizard from "./ClientProfileWizard.tsx";
import { useProfileSession } from "./hooks/useProfileSession.ts";
import type { FetchLike } from "./lib/clientProfileApi.ts";
import type { ProfileSession } from "./lib/profileSession.ts";
import type { WizardState } from "./lib/wizardState.ts";

export interface ClientProfileOnboardingProps {
  /**
   * "server" (default): read and save through /api/organization/client-profile;
   * the server decides whose profile it is. "demo": fictional sample data, no
   * request is made and nothing is saved. This is chosen by the code that mounts
   * the page, never by a URL parameter, a stored value or a user-picked id.
   */
  source?: "server" | "demo";
  /** Test seam: replace `fetch` (same-origin credentials are still set by the client). */
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
export default function ClientProfileOnboardingPage({ source = "server", fetchImpl, initialSession, initialState }: ClientProfileOnboardingProps) {
  const { session, save, retry } = useProfileSession(source === "server", fetchImpl, initialSession);

  if (source === "demo") return <ClientProfileWizard initialState={initialState} />;
  if (session.phase === "loading") return <LoadingPanel />;
  if (session.phase === "load_failed") return <LoadFailedPanel code={session.code} onRetry={retry} />;

  return (
    <>
      {session.mode === "create" ? <NoSavedProfileNote /> : null}
      {/* Remounts only when a (re)load completes; the form's own saves and edits never reset it. */}
      <ClientProfileWizard key={session.version} onSave={save} initialState={{ draft: session.draft, ...initialState }} />
    </>
  );
}
