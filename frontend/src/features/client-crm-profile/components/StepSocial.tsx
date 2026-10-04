import { LIMITS, SOCIAL_PLATFORMS } from "../contracts/clientProfileDraft.ts";
import { PLATFORM_LABEL } from "../lib/validateProfile.ts";
import { BUTTON_SECONDARY, SelectField, TextField } from "./Fields.tsx";
import { StepHeading, type StepProps } from "./StepChrome.tsx";

const PLATFORM_OPTIONS = SOCIAL_PLATFORMS.map((value) => ({ value, label: PLATFORM_LABEL[value] }));

/** Shown next to every account so a typed handle is never mistaken for a connection. */
export function DetailsOnlyBadge() {
  return (
    <span data-details-only className="inline-flex items-center rounded border border-zinc-500 bg-zinc-800 px-2 py-0.5 text-xs text-zinc-100">
      Details only. Not connected.
    </span>
  );
}

export function StepSocial({ state, dispatch, errorFor }: StepProps) {
  const { draft } = state;
  const blur = (path: string) => () => dispatch({ type: "blur", path });

  return (
    <div className="space-y-5">
      <StepHeading step="social">Optional. Record where your brand appears online.</StepHeading>

      <div role="note" data-social-notice className="space-y-1 rounded-lg border border-violet-400/60 bg-violet-500/10 p-3 text-sm text-violet-100">
        <p className="font-semibold">These are details you type, not connected accounts.</p>
        <p>
          A handle or link is plain profile information only. It is not verified and gives MarketOS no access to the account.
          Never enter a password, access token, API key or any other secret. Anything that looks like one is rejected.
        </p>
      </div>

      <ol className="space-y-4">
        {draft.socialAccounts.map((account, index) => {
          const base = `socialAccounts.${index}`;
          return (
            <li key={account.key}>
              <fieldset className="min-w-0 space-y-3 rounded-lg border border-zinc-700 bg-zinc-900/40 p-3 sm:p-4">
                <legend className="px-1 text-sm font-semibold text-zinc-100">Account {index + 1}</legend>
                <p><DetailsOnlyBadge /></p>
                <p className="text-xs text-zinc-300">Provide a handle, a public profile link, or both.</p>
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  <SelectField
                    path={`${base}.platform`}
                    label="Platform"
                    required
                    value={account.platform}
                    options={PLATFORM_OPTIONS}
                    error={errorFor(`${base}.platform`)}
                    onChange={(value) => dispatch({ type: "updateSocial", key: account.key, patch: { platform: value } })}
                    onBlur={blur(`${base}.platform`)}
                  />
                  <TextField
                    path={`${base}.handle`}
                    label="Handle"
                    marker="none"
                    technical
                    value={account.handle}
                    maxLength={LIMITS.handleMax + 10}
                    hint="For example @yourbrand."
                    error={errorFor(`${base}.handle`)}
                    onChange={(value) => dispatch({ type: "updateSocial", key: account.key, patch: { handle: value } })}
                    onBlur={blur(`${base}.handle`)}
                  />
                </div>
                <TextField
                  path={`${base}.url`}
                  label="Public profile link"
                  marker="none"
                  technical
                  inputMode="url"
                  value={account.url}
                  maxLength={LIMITS.urlMax + 20}
                  hint="A plain public link starting with https://. No logins, tokens or private links."
                  error={errorFor(`${base}.url`)}
                  onChange={(value) => dispatch({ type: "updateSocial", key: account.key, patch: { url: value } })}
                  onBlur={blur(`${base}.url`)}
                />
                <TextField
                  path={`${base}.notes`}
                  label="Notes"
                  value={account.notes}
                  maxLength={LIMITS.notesMax + 20}
                  hint="For example the audience or how the account is used."
                  error={errorFor(`${base}.notes`)}
                  onChange={(value) => dispatch({ type: "updateSocial", key: account.key, patch: { notes: value } })}
                  onBlur={blur(`${base}.notes`)}
                />
                <button
                  type="button"
                  className={BUTTON_SECONDARY}
                  aria-label={`Remove account ${index + 1}${account.handle.trim() ? `: ${account.handle.trim()}` : ""}`}
                  onClick={() => dispatch({ type: "removeSocial", key: account.key })}
                >
                  Remove
                </button>
              </fieldset>
            </li>
          );
        })}
      </ol>
      {draft.socialAccounts.length === 0 ? <p className="text-sm text-zinc-300">No accounts added. You can skip this step.</p> : null}

      <button
        type="button"
        id="cp-socialAccounts-add"
        className={BUTTON_SECONDARY}
        disabled={draft.socialAccounts.length >= LIMITS.maxSocialAccounts}
        onClick={() => dispatch({ type: "addSocial" })}
      >
        Add account details
      </button>
    </div>
  );
}
