import type { ReactNode } from "react";
import { BUSINESS_TYPE_META, STEP_META, type StepId } from "../contracts/clientProfileDraft.ts";
import { demoReviewedNow, saveView, type SaveView } from "../lib/wizardState.ts";
import { focusId } from "../lib/focusTargets.ts";
import { PLATFORM_LABEL, stepOfPath } from "../lib/validateProfile.ts";
import { BUTTON_PRIMARY, BUTTON_SECONDARY, WRAP } from "./Fields.tsx";
import { DetailsOnlyBadge } from "./StepSocial.tsx";
import { ERROR_SUMMARY_ID, StepHeading, type StepProps } from "./StepChrome.tsx";
import { SAVE_ERROR_TEXT } from "../lib/errorCopy.ts";
import { NOT_PROVIDED } from "../lib/text.ts";

const AVAILABILITY_TEXT = { in_stock: "In stock", made_to_order: "Made to order", dropship: "Dropshipped", preorder: "Pre-order", unknown: "Not sure" } as const;
const DELIVERY_TEXT = { remote: "Remote", on_site: "On site", hybrid: "Remote and on site" } as const;

function Section({ step, title, children, onEdit }: { step: StepId; title: string; children: ReactNode; onEdit: () => void }) {
  return (
    <section aria-labelledby={`cp-review-${step}`} data-review-section={step} className="min-w-0 space-y-2 rounded-lg border border-zinc-800 bg-zinc-900/40 p-3 sm:p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id={`cp-review-${step}`} className="text-sm font-semibold text-zinc-100">{title}</h3>
        <button type="button" className={BUTTON_SECONDARY} aria-label={`Edit ${title}`} onClick={onEdit}>Edit</button>
      </div>
      {children}
    </section>
  );
}

function Row({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-zinc-400">{term}</dt>
      <dd className={`text-sm text-zinc-100 ${WRAP}`}>{children}</dd>
    </div>
  );
}

const list = (values: readonly string[]) => (values.length > 0 ? values.join(", ") : NOT_PROVIDED);

const SAVE_COPY: Record<SaveView, { title: string; body: string }> = {
  demo: { title: "Demo only: not saved", body: "Nothing you entered is stored or sent anywhere. Saving needs a secure, signed-in storage service that is not connected to this page." },
  unsaved: { title: "Not saved yet", body: "Confirm below to save this profile." },
  saving: { title: "Saving", body: "Please wait. Your entries are kept." },
  saved: { title: "Profile saved", body: "The server accepted the save, and the saved profile matches what you see here." },
  changed_since_saved: { title: "Changed since last save", body: "The saved profile is older than what you see here. Confirm again to save the changes." },
  error: { title: "Saving failed", body: "Your entries are still here." },
};

export function StepReview({
  state,
  validation,
  dispatch,
  persistenceAvailable,
}: StepProps & { persistenceAvailable: boolean }) {
  const { draft } = state;
  const meta = draft.businessType ? BUSINESS_TYPE_META[draft.businessType] : null;
  const view = saveView(state, persistenceAvailable);
  const copy = SAVE_COPY[view];
  const saving = state.save.status === "saving";
  const edit = (step: StepId) => () => dispatch({ type: "goto", step });
  const reviewedInDemo = !persistenceAvailable && demoReviewedNow(state);
  const missing = validation.errors;

  return (
    <div className="space-y-5">
      <StepHeading step="review">Check everything, then confirm. Missing information is listed first.</StepHeading>

      <section
        id={ERROR_SUMMARY_ID}
        tabIndex={-1}
        aria-labelledby="cp-missing-heading"
        data-missing-info={missing.length}
        className={`rounded-lg border p-3 text-sm focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400 ${
          missing.length > 0 ? "border-amber-500/60 bg-amber-500/10 text-amber-100" : "border-emerald-500/50 bg-emerald-500/10 text-emerald-100"
        }`}
      >
        <h3 id="cp-missing-heading" className="font-semibold">
          {missing.length === 0 ? "All required information is present" : `Missing or invalid information (${missing.length})`}
        </h3>
        {missing.length > 0 ? (
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {missing.map((error, index) => (
              <li key={`${error.path}-${index}`} className={WRAP}>
                <span className="text-xs uppercase tracking-wide opacity-80">{STEP_META[stepOfPath(error.path)].short}: </span>
                <a
                  href={`#${focusId(error.path)}`}
                  className="underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-200"
                  onClick={(event) => {
                    event.preventDefault();
                    dispatch({ type: "goto", step: stepOfPath(error.path), path: error.path });
                  }}
                >
                  {error.message}
                </a>
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <section aria-labelledby="cp-saved-heading" data-panel="saved-profile" data-save-view={view} className="min-w-0 space-y-1 rounded-lg border border-zinc-700 bg-zinc-900/60 p-3 text-sm">
          <h3 id="cp-saved-heading" className="text-xs font-semibold uppercase tracking-wide text-zinc-300">Saved profile</h3>
          <p className="font-medium text-zinc-50">{copy.title}</p>
          <p className="text-zinc-300">{view === "error" && state.save.status === "error" ? `${SAVE_ERROR_TEXT[state.save.code]} Your entries are still here.` : copy.body}</p>
          {reviewedInDemo ? <p data-demo-reviewed className="text-violet-200">Reviewed in demo mode. Nothing was saved or sent.</p> : null}
        </section>
        <section aria-labelledby="cp-connected-heading" data-panel="connected-accounts" className="min-w-0 space-y-1 rounded-lg border border-zinc-700 bg-zinc-900/60 p-3 text-sm">
          <h3 id="cp-connected-heading" className="text-xs font-semibold uppercase tracking-wide text-zinc-300">Connected external accounts</h3>
          <p className="font-medium text-zinc-50">Nothing connected by this page</p>
          <p className="text-zinc-300">
            This page cannot connect an account. Handles and links are plain details you typed. They are not verified and give MarketOS no access.
          </p>
        </section>
      </div>

      <Section step="company" title="Company and business model" onEdit={edit("company")}>
        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Row term="Company name">{draft.companyName.trim() || NOT_PROVIDED}</Row>
          <Row term="Business type">{meta?.label ?? NOT_PROVIDED}</Row>
        </dl>
      </Section>

      <Section step="audience" title="Categories, segments and markets" onEdit={edit("audience")}>
        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Row term="Categories">{list(draft.categories)}</Row>
          <Row term={meta?.segmentsLabel ?? "Segments"}>{list(draft.segments)}</Row>
          <Row term="Target markets">{list(draft.targetMarkets)}</Row>
        </dl>
      </Section>

      <Section step="offerings" title={`Offerings (${draft.offerings.length})`} onEdit={edit("offerings")}>
        {draft.offerings.length === 0 ? <p className="text-sm text-zinc-300">{NOT_PROVIDED}</p> : (
          <ul className="space-y-2">
            {draft.offerings.map((offering, index) => (
              <li key={offering.key} className={`rounded border border-zinc-800 bg-zinc-950/40 p-2 text-sm text-zinc-100 ${WRAP}`}>
                <p className="font-medium">{offering.name.trim() || `Offering ${index + 1}: ${NOT_PROVIDED}`}</p>
                {offering.description.trim() ? <p className="text-zinc-300">{offering.description.trim()}</p> : null}
                {meta && !meta.tracksInventory ? (
                  <p className="text-xs text-zinc-300">Delivery: {offering.delivery ? DELIVERY_TEXT[offering.delivery] : NOT_PROVIDED}</p>
                ) : null}
                {meta?.tracksInventory ? (
                  <p className="text-xs text-zinc-300">
                    Availability: {offering.availability ? AVAILABILITY_TEXT[offering.availability] : NOT_PROVIDED}
                    {" · "}SKU: {offering.sku.trim() || NOT_PROVIDED}
                    {" · "}Units on hand (self-reported): {offering.quantity.trim() || NOT_PROVIDED}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section step="social" title={`Social account details (${draft.socialAccounts.length})`} onEdit={edit("social")}>
        {draft.socialAccounts.length === 0 ? <p className="text-sm text-zinc-300">None added (optional).</p> : (
          <ul className="space-y-2">
            {draft.socialAccounts.map((account, index) => (
              <li key={account.key} className={`rounded border border-zinc-800 bg-zinc-950/40 p-2 text-sm text-zinc-100 ${WRAP}`}>
                <p className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{account.platform ? PLATFORM_LABEL[account.platform] : `Account ${index + 1}: ${NOT_PROVIDED}`}</span>
                  <DetailsOnlyBadge />
                </p>
                <p className="text-zinc-300">Handle: {account.handle.trim() || NOT_PROVIDED}</p>
                <p className="text-zinc-300">Link: {account.url.trim() || NOT_PROVIDED}</p>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <div className="flex flex-col gap-2 border-t border-zinc-800 pt-4 sm:flex-row sm:justify-between">
        <button type="button" className={BUTTON_SECONDARY} onClick={() => dispatch({ type: "back" })}>Back</button>
        <button type="submit" className={BUTTON_PRIMARY} aria-disabled={saving ? true : undefined} data-confirm>
          {saving ? "Saving…" : persistenceAvailable ? (state.savedKey !== null ? "Save profile again" : "Confirm and save profile") : "Confirm review (demo, not saved)"}
        </button>
      </div>
    </div>
  );
}
