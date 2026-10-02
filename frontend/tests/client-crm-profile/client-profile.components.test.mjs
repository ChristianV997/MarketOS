/**
 * Client CRM profile: component tests.
 *
 * The REAL components are rendered with react-dom/server and the DOM is asserted
 * (labels, aria wiring, roles, states, copy). State-driven behaviour (Next
 * gating, focus requests, add/remove, saved-vs-demo) is covered by the reducer
 * tests in client-profile.logic.test.mjs. There is no DOM test environment in
 * this repo, so event-level keyboard behaviour is verified separately in a real
 * browser (not part of this suite).
 */
import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

import { FEATURE_ROOT, importFeature } from "./load.mjs";

const Page = (await importFeature("ClientProfileWizard.tsx")).default;
const { initialWizardState, wizardReducer, EMPTY_DRAFT } = await importFeature("lib/wizardState.ts");
const { validateProfile } = await importFeature("lib/validateProfile.ts");
const { focusId } = await importFeature("lib/focusTargets.ts");
const { buildPayload, payloadKey } = await importFeature("lib/toPayload.ts");
const { storedKey } = await importFeature("lib/toServerBody.ts");
const featureIndex = await importFeature("index.ts");

// ------------------------------------------------------------ helpers

const offering = (over = {}) => ({ key: "o1", name: "Item", description: "", delivery: "", availability: "", sku: "", quantity: "", ...over });
const account = (over = {}) => ({ key: "s1", platform: "instagram", handle: "example_demo", url: "", notes: "", ...over });
const productDraft = (over = {}) => ({
  companyName: "Example Demo Co",
  businessType: "product",
  categories: ["Coffee equipment"],
  segments: ["Home baristas"],
  targetMarkets: ["Canada"],
  offerings: [offering({ name: "Kettle", availability: "in_stock", quantity: "5" })],
  socialAccounts: [account()],
  ...over,
});
const serviceDraft = (type = "service_b2b", over = {}) =>
  productDraft({ businessType: type, offerings: [offering({ name: "Bookkeeping", delivery: "remote" })], ...over });

const render = (props = {}, state = {}) => renderToStaticMarkup(createElement(Page, { ...props, initialState: state }));
const asStep = (step, draft, extra = {}, props = {}) => render(props, { step, draft, ...extra });

const all = (html, re) => html.match(re) ?? [];
const tagsOf = (html, name, filter = () => true) => all(html, new RegExp(`<${name}\\b[^>]*>`, "g")).filter(filter);
// HTML attribute names are case-insensitive; React serializes some in camelCase (autoComplete, inputMode).
const attr = (tag, name) => new RegExp(`\\s${name}="([^"]*)"`, "i").exec(tag)?.[1] ?? null;
const has = (tag, name) => new RegExp(`\\s${name}(=""|=|\\s|/?>)`, "i").test(tag);
const text = (html) =>
  html.replace(/<[^>]+>/g, " ").replace(/&quot;/g, '"').replace(/&#x27;/g, "'").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/\s+/g, " ");
const ids = (html) => all(html, /\sid="([^"]+)"/g).map((m) => /id="([^"]+)"/.exec(m)[1]);

// ------------------------------------------------------------ first render (demo)

test("first render: client view, demo banner, one h1, guided steps, live region, native form", () => {
  const html = render();
  assert.match(text(html), /Client view/);
  assert.equal(all(html, /<h1\b/g).length, 1);
  assert.match(text(html), /Company profile/);
  assert.match(html, /data-mode="demo"/);
  assert.match(text(html), /Demo mode\. Nothing is saved or sent\./);
  assert.match(text(html), /No real client information is loaded/);
  assert.match(text(html), /does not load information about any other company and has no owner controls/);

  const live = tagsOf(html, "p", (t) => has(t, "data-live-summary"))[0];
  assert.equal(attr(live, "role"), "status");
  assert.equal(attr(live, "aria-live"), "polite");
  assert.equal(attr(live, "aria-atomic"), "true");

  const form = tagsOf(html, "form")[0];
  assert.ok(has(form, "novalidate"), "browser bubbles are replaced by inline errors");
  assert.equal(attr(form, "aria-label"), "Profile steps");
});

test("step navigation: five buttons, current step marked, accessible names carry number and status", () => {
  const html = render();
  const nav = tagsOf(html, "nav")[0];
  assert.equal(attr(nav, "aria-label"), "Profile sections");
  const steps = tagsOf(html, "button", (t) => attr(t, "data-step") !== null);
  assert.deepEqual(steps.map((t) => attr(t, "data-step")), ["company", "audience", "offerings", "social", "review"]);
  assert.deepEqual(steps.map((t) => attr(t, "aria-current")), ["step", null, null, null, null]);
  assert.equal(attr(steps[0], "aria-label"), "Step 1 of 5: Company. Not complete.");
  assert.equal(attr(steps[3], "aria-label"), "Step 4 of 5: Social. Optional, none added.");
  assert.ok(steps.every((t) => attr(t, "type") === "button"), "step buttons never submit the form");
});

test("step nav status reflects attempts and completion", () => {
  const attempted = asStep("company", EMPTY_DRAFT, { attempted: ["company"] });
  assert.match(attempted, /aria-label="Step 1 of 5: Company\. Needs attention \(2\)\./);
  const done = asStep("company", productDraft());
  assert.match(done, /aria-label="Step 1 of 5: Company\. Complete\./);
  assert.match(done, /aria-label="Step 3 of 5: Offerings\. Complete\./);
});

test("company step: every visible label points at a real control; business type is a labelled radio group", () => {
  const html = render();
  const labelTargets = tagsOf(html, "label").map((t) => attr(t, "for")).filter(Boolean);
  const idSet = new Set(ids(html));
  for (const target of labelTargets) assert.ok(idSet.has(target), `label for=${target} has a control`);

  assert.match(html, /<legend[^>]*>\s*Business type/);
  const radios = tagsOf(html, "input", (t) => attr(t, "type") === "radio");
  assert.equal(radios.length, 4);
  assert.deepEqual(radios.map((t) => attr(t, "value")), ["service_b2c", "service_b2b", "product", "other"], "every business type the service accepts");
  assert.ok(radios.every((t) => attr(t, "name") === "businessType"));
  assert.ok(radios.every((t) => !has(t, "checked")), "nothing is preselected");
  assert.match(text(html), /Service for consumers \(B2C\)/);
  assert.match(text(html), /Service for businesses \(B2B\)/);
  assert.match(text(html), /Product business/);
  assert.match(text(html), /Other business model/);
});

test("no field can hold a secret: no password inputs, autocomplete off, plain text inputs", () => {
  for (const step of ["company", "audience", "offerings", "social"]) {
    const html = asStep(step, productDraft({ offerings: [offering({ availability: "in_stock" })], socialAccounts: [account()] }));
    assert.equal(tagsOf(html, "input", (t) => attr(t, "type") === "password").length, 0, step);
    const textInputs = tagsOf(html, "input", (t) => attr(t, "type") === "text");
    assert.ok(textInputs.length > 0, step);
    assert.ok(textInputs.every((t) => attr(t, "autocomplete") === "off"), `${step}: autocomplete off`);
  }
});

// ------------------------------------------------------------ inline errors

test("errors are hidden on a fresh form and shown with full aria wiring after Next is attempted", () => {
  assert.equal(all(render(), /data-field-error/g).length, 0);
  assert.equal(all(render(), /data-error-summary/g).length, 0);

  const html = asStep("company", EMPTY_DRAFT, { attempted: ["company"] });
  const summary = tagsOf(html, "section", (t) => has(t, "data-error-summary"))[0];
  assert.equal(attr(summary, "role"), null, "a focused, named region: a live alert would re-announce on every fix");
  assert.equal(attr(summary, "aria-labelledby"), "cp-error-summary-heading");
  assert.equal(attr(summary, "tabindex"), "-1");
  assert.match(text(html), /There are 2 problems to fix/);
  assert.match(html, /href="#cp-companyName"/);
  assert.match(html, /href="#cp-businessType"/);

  const input = tagsOf(html, "input", (t) => attr(t, "name") === "companyName")[0];
  assert.equal(attr(input, "aria-invalid"), "true");
  assert.equal(attr(input, "aria-required"), "true");
  const described = attr(input, "aria-describedby").split(" ");
  assert.ok(described.includes("cp-companyName-error") && described.includes("cp-companyName-hint"));
  assert.ok(ids(html).includes("cp-companyName-error"));
  assert.match(text(html), /Error: Enter your company name\./);
  assert.match(text(html), /Error: Choose the business type that fits best\./);
});

test("leaving a field shows only that field's error", () => {
  const html = asStep("company", EMPTY_DRAFT, { touched: ["companyName"] });
  assert.match(text(html), /Error: Enter your company name\./);
  assert.doesNotMatch(text(html), /Choose the business type/);
  assert.equal(all(html, /data-error-summary/g).length, 0, "the summary needs an attempted Next");
});

test("every error-summary target exists in the rendered step (links can move focus)", () => {
  const invalid = {
    companyName: "",
    businessType: "product",
    categories: [],
    segments: [],
    targetMarkets: [],
    offerings: [offering({ name: "", availability: "", quantity: "abc", sku: "<>" })],
    socialAccounts: [account({ platform: "", handle: "", url: "http://insecure" })],
  };
  const validation = validateProfile(invalid);
  const steps = ["company", "audience", "offerings", "social"];
  for (const step of steps) {
    const html = asStep(step, invalid, { attempted: [step] });
    const present = new Set(ids(html));
    assert.ok(validation.byStep[step].length > 0, step);
    for (const error of validation.byStep[step]) {
      assert.ok(present.has(focusId(error.path)), `${step}: ${error.path} -> #${focusId(error.path)}`);
    }
  }
  assert.equal(focusId("offerings"), "cp-offerings-add");
});

// ------------------------------------------------------------ type-dependent steps

test("audience step: labels and hints follow the business type", () => {
  assert.match(text(asStep("audience", serviceDraft("service_b2c"))), /Customer segments/);
  const b2b = text(asStep("audience", serviceDraft("service_b2b")));
  assert.match(b2b, /Buyer segments/);
  assert.match(b2b, /mid-market SaaS/);
  assert.match(text(asStep("audience", productDraft())), /coffee equipment/);
  const none = asStep("audience", { ...EMPTY_DRAFT });
  assert.match(none, /role="note"/);
  assert.match(text(none), /Choose a business type in step 1/);
});

test("audience step: chip lists are labelled, removable per entry and show counts", () => {
  const html = asStep("audience", productDraft({ categories: ["Coffee equipment", "Tea"] }));
  assert.match(html, /aria-label="Categories added"/);
  assert.match(html, /aria-label="Remove category Coffee equipment"/);
  assert.match(html, /aria-label="Remove category Tea"/);
  assert.match(text(html), /2 of 10 categories\./);
  assert.match(text(html), /Press Enter or choose Add/);
  const empty = asStep("audience", EMPTY_DRAFT);
  assert.equal(all(text(empty), /None added yet\./g).length, 3);
});

test("offerings step for a service: delivery is asked; inventory fields are absent", () => {
  const html = asStep("offerings", serviceDraft("service_b2b"));
  assert.match(text(html), /How is it delivered\?/);
  assert.match(html, /<option value="on_site">On site<\/option>/);
  assert.doesNotMatch(text(html), /Availability|Units on hand|SKU/);
  assert.match(text(html), /Add service/);
  assert.match(html, /aria-label="Remove service 1: Bookkeeping"/);
});

test("offerings step for a product: availability, SKU and self-reported units are asked; delivery is absent", () => {
  const html = asStep("offerings", productDraft());
  assert.match(text(html), /Availability \(optional\)/);
  assert.match(html, /<option value="unknown">Not sure<\/option>/);
  assert.match(text(html), /SKU \(optional\)/);
  assert.match(text(html), /Units on hand \(optional\)/);
  assert.match(text(html), /Self-reported and not verified\. Leave empty if unknown\./);
  assert.doesNotMatch(text(html), /How is it delivered/);
  assert.match(text(html), /Add product/);
  const qty = tagsOf(html, "input", (t) => attr(t, "name") === "offerings.0.quantity")[0];
  assert.equal(attr(qty, "inputmode"), "numeric");
  assert.equal(attr(qty, "value"), "5", "an unreported quantity would be empty, never 0");
  const blank = asStep("offerings", productDraft({ offerings: [offering({ availability: "in_stock", quantity: "" })] }));
  assert.equal(attr(tagsOf(blank, "input", (t) => attr(t, "name") === "offerings.0.quantity")[0], "value"), "");
});

test("offerings step without a business type asks for one instead of guessing", () => {
  const html = asStep("offerings", { ...EMPTY_DRAFT, offerings: [offering()] });
  assert.match(text(html), /Choose a business type in step 1/);
  assert.match(text(html), /Add product or service/);
  assert.doesNotMatch(text(html), /Availability|How is it delivered/);
});

test("empty offering list reports the required-list error against the Add button target", () => {
  const html = asStep("offerings", productDraft({ offerings: [] }), { attempted: ["offerings"] });
  assert.match(text(html), /Error: Add at least one product\./);
  assert.match(html, /href="#cp-offerings-add"/);
  assert.ok(ids(html).includes("cp-offerings-add"));
});

// ------------------------------------------------------------ social: saved details vs connected accounts

test("social step: details-only notice, badge on every account, no connect affordance", () => {
  const html = asStep("social", productDraft({ socialAccounts: [account(), account({ key: "s2", platform: "tiktok", handle: "other_demo" })] }));
  assert.match(text(html), /These are details you type, not connected accounts\./);
  assert.match(text(html), /gives MarketOS no access to the account/);
  assert.match(text(html), /Never enter a password, access token, API key or any other secret/);
  assert.equal(all(html, /data-details-only/g).length, 2);
  assert.equal(all(text(html), /Details only\. Not connected\./g).length, 2);
  const buttons = tagsOf(html, "button").length;
  assert.ok(buttons > 0);
  assert.doesNotMatch(text(html), /\b(Connect|Authorize|Log in|Sign in with|Link account|Verify)\b/);
  assert.match(text(html), /Add account details/);
  assert.match(html, /aria-label="Remove account 1: example_demo"/);
});

test("social step: the handle-or-link rule is stated once, and neither field claims to be optional", () => {
  const html = asStep("social", productDraft());
  assert.match(text(html), /Provide a handle, a public profile link, or both\./);
  const labels = tagsOf(html, "label").length;
  assert.ok(labels >= 4);
  assert.doesNotMatch(text(html), /Handle \(optional\)|Public profile link \(optional\)/);
  assert.match(text(html), /Notes \(optional\)/);
  const badge = html.indexOf("data-details-only");
  const legendEnd = html.indexOf("</legend>");
  assert.ok(badge > legendEnd, "the badge sits outside the legend so it is not part of every field's group name");
});

test("technical fields turn off auto-capitalisation and spell-check; names and prose keep the defaults", () => {
  const social = asStep("social", productDraft());
  const handle = tagsOf(social, "input", (t) => attr(t, "name") === "socialAccounts.0.handle")[0];
  assert.equal(attr(handle, "autoCapitalize"), "off");
  assert.equal(attr(handle, "spellcheck"), "false");
  const company = tagsOf(render(), "input", (t) => attr(t, "name") === "companyName")[0];
  assert.equal(attr(company, "autoCapitalize"), null);
  assert.equal(attr(company, "spellcheck"), null);
});

test("required is exposed once to assistive tech: aria-required on the control, visible marker hidden from it", () => {
  const html = render();
  assert.match(html, /<span aria-hidden="true" class="text-zinc-300"> \(required\)<\/span>/);
  assert.equal(attr(tagsOf(html, "input", (t) => attr(t, "name") === "companyName")[0], "aria-required"), "true");
  assert.match(html, /aria-describedby="cp-businessType-hint"/);
});

test("text left in a tag box is shown in the box and reported when Next is attempted", () => {
  const html = asStep("audience", productDraft(), { attempted: ["audience"], pending: { categories: "Half typed", segments: "", targetMarkets: "" } });
  const input = tagsOf(html, "input", (t) => attr(t, "name") === "categories")[0];
  assert.equal(attr(input, "value"), "Half typed");
  assert.match(text(html), /There is text in the category box that has not been added\. Choose Add category, or clear the box\./);
  assert.match(html, /href="#cp-categories"/);
  const errorTag = tagsOf(html, "p", (t) => attr(t, "id") === "cp-categories-error")[0];
  assert.ok(!attr(errorTag, "role"), "a validation error is announced by the error summary that takes focus; only errors raised while typing in the box are alerts");
  assert.equal(attr(tagsOf(html, "input", (t) => attr(t, "name") === "categories")[0], "aria-invalid"), "true");
  assert.match(attr(tagsOf(html, "input", (t) => attr(t, "name") === "categories")[0], "aria-describedby"), /cp-categories-error/);
});

test("offerings step reminds which detail each entry needs for the chosen type", () => {
  assert.match(text(asStep("offerings", productDraft())), /Business type: Product business\. Availability is optional\. Details typed for another type are kept but not saved\./);
  assert.match(text(asStep("offerings", serviceDraft("service_b2c"))), /Delivery is optional\./);
  assert.doesNotMatch(text(asStep("offerings", productDraft({ offerings: [] }))), /Business type: /);
});

test("demo tools do not show a replace prompt until asked; the form has its own accessible name", () => {
  const html = render();
  assert.doesNotMatch(html, /data-replace-confirm/);
  assert.equal(attr(tagsOf(html, "form")[0], "aria-label"), "Profile steps");
  assert.doesNotMatch(html, /aria-labelledby="cp-page-heading"[^>]*novalidate/i, "the section and the form must not share a name");
});

test("social step: optional and skippable when empty; platform options are the supported set", () => {
  const html = asStep("social", productDraft({ socialAccounts: [] }));
  assert.match(text(html), /No accounts added\. You can skip this step\./);
  const withAccount = asStep("social", productDraft());
  for (const label of ["Instagram", "TikTok", "Facebook", ">X<", "LinkedIn", "YouTube", "Pinterest", "Other"]) {
    assert.ok(withAccount.includes(label.startsWith(">") ? label : `>${label}</option>`), label);
  }
  assert.match(text(withAccount), /Public profile link/);
  assert.match(text(withAccount), /No logins, tokens or private links/);
});

// ------------------------------------------------------------ review

test("review with missing information lists each item with a link and keeps Confirm reachable", () => {
  const html = asStep("review", { ...EMPTY_DRAFT, companyName: "Example Demo Co" });
  assert.match(text(html), /Missing or invalid information \(4\)/);
  assert.match(html, /data-missing-info="4"/);
  for (const message of ["Choose the business type that fits best.", "Add at least one entry for segments.", "Add at least one target market.", "Add at least one product or service."]) {
    assert.match(text(html), new RegExp(message.replace(/[.]/g, "\\.")));
  }
  assert.match(html, /href="#cp-businessType"/);
  const section = tagsOf(html, "section", (t) => attr(t, "id") === "cp-error-summary")[0];
  assert.equal(attr(section, "tabindex"), "-1", "focus can be sent here after a failed Confirm");
  const confirm = tagsOf(html, "button", (t) => has(t, "data-confirm"))[0];
  assert.equal(attr(confirm, "type"), "submit");
  assert.ok(!has(confirm, "disabled"), "a failed Confirm explains itself instead of being a dead button");
  assert.match(text(html), /Not provided/);
});

test("review of a complete profile in demo mode: not saved, nothing connected, demo-labelled Confirm", () => {
  const html = asStep("review", productDraft());
  assert.match(text(html), /All required information is present/);
  assert.match(html, /data-panel="saved-profile"[^>]*data-save-view="demo"/);
  assert.match(text(html), /Demo only: not saved/);
  assert.match(text(html), /Saving needs a signed-in connection to the profile service/);
  assert.doesNotMatch(text(html), /tenant/i, "no engineering jargon in client-facing copy");
  assert.match(text(html), /Connected external accounts Nothing connected by this page/);
  assert.match(text(html), /This page cannot connect an account/);
  assert.match(text(html), /Confirm review \(demo, not saved\)/);
  assert.doesNotMatch(text(html), /Profile saved|Confirm and save/);
  assert.match(text(html), /Units on hand \(self-reported\): 5/);
  assert.match(text(html), /Details only\. Not connected\./);
});

test("demo confirmation is worded as a review, never as a save, and lapses when the form changes", () => {
  const draft = productDraft();
  const key = payloadKey(buildPayload(draft));
  const html = asStep("review", draft, { demoReviewedKey: key });
  assert.match(text(html), /Reviewed in demo mode\. Nothing was saved or sent\./);
  const changed = asStep("review", productDraft({ companyName: "Changed Demo Co" }), { demoReviewedKey: key });
  assert.doesNotMatch(text(changed), /Reviewed in demo mode/);
});

test("review shows the type-relevant summary only", () => {
  const service = text(asStep("review", serviceDraft("service_b2b", { offerings: [offering({ name: "Audit", delivery: "hybrid", sku: "S-1", quantity: "9", availability: "in_stock" })] })));
  assert.match(service, /Delivery: Remote and on site/);
  assert.doesNotMatch(service, /SKU|Units on hand|Availability/);
  assert.match(service, /Buyer segments/);
});

// ------------------------------------------------------------ persistence available (MOCKED save function)

test("with a save function the demo banner is replaced and Confirm says it saves", () => {
  const props = { onSave: async () => {} };
  const html = asStep("review", productDraft(), {}, props);
  assert.match(html, /data-mode="persistent"/);
  assert.doesNotMatch(html, /data-mode="demo"/);
  assert.doesNotMatch(text(html), /Fill with fictional sample data/);
  assert.match(text(html), /Confirm and save profile/);
  assert.match(html, /data-save-view="unsaved"/);
  assert.match(text(html), /Not saved yet/);
});

test("saved / changed / saving / failed states each use their own wording and never over-claim", () => {
  const props = { onSave: async () => {} };
  const draft = productDraft();
  const key = storedKey(buildPayload(draft));
  const saved = asStep("review", draft, { savedKey: key, save: { status: "saved" } }, props);
  assert.match(html2(saved, "saved"), /Profile saved/);
  const changed = asStep("review", productDraft({ companyName: "Renamed Demo Co" }), { savedKey: key, save: { status: "saved" } }, props);
  assert.match(changed, /data-save-view="changed_since_saved"/);
  assert.match(text(changed), /Changed since last save/);
  assert.doesNotMatch(text(changed), /Profile saved/);
  const saving = asStep("review", draft, { save: { status: "saving" } }, props);
  assert.match(text(saving), /Saving…/);
  const savingButton = tagsOf(saving, "button", (t) => has(t, "data-confirm"))[0];
  assert.equal(attr(savingButton, "aria-disabled"), "true", "aria-disabled keeps focus on the button while saving");
  assert.ok(!has(savingButton, "disabled"));
  const seen = new Set();
  for (const [code, message] of [
    ["unauthenticated", /not signed in/],
    ["content_rejected", /content screen rejected a value/],
    ["forbidden", /not allowed to save/],
    ["not_found", /service could not be found/],
    ["conflict", /changed elsewhere/],
    ["unavailable", /unavailable right now/],
    ["malformed_response", /could not read, so it cannot confirm anything was saved/],
    ["network", /could not be reached/],
    ["validation", /server rejected some values/],
    ["unknown", /Something went wrong/],
  ]) {
    const failed = asStep("review", draft, { save: { status: "error", code } }, props);
    assert.match(failed, /data-save-view="error"/);
    assert.match(text(failed), /Saving failed/);
    assert.match(text(failed), message, code);
    assert.match(text(failed), /Your entries are still here/);
    assert.doesNotMatch(text(failed), /Profile saved/, code);
    seen.add(text(failed.match(/data-panel="saved-profile".*?<\/section>/s)[0]));
  }
  assert.equal(seen.size, 10, "every failure code reads differently");
});

test("a failed save is also shown right above Confirm, so it is seen where the button was pressed", () => {
  const html = asStep("review", productDraft(), { save: { status: "error", code: "unavailable" } }, { onSave: async () => {} });
  const at = html.indexOf("data-save-error=");
  assert.ok(at > 0 && at < html.indexOf("data-confirm"), "the message precedes the Confirm button");
  assert.match(text(html.slice(at, html.indexOf("data-confirm"))), /unavailable right now.*Your entries are still here/);
  assert.doesNotMatch(html.slice(at - 80, at + 40), /role="alert"/, "the live region announces it; no second alert");
  assert.doesNotMatch(asStep("review", productDraft(), {}, { onSave: async () => {} }), /data-save-error/);
});
const html2 = (html, view) => {
  assert.match(html, new RegExp(`data-save-view="${view}"`));
  return text(html);
};

test("even with a save function, the connected-accounts panel never claims a connection", () => {
  const html = asStep("review", productDraft(), {}, { onSave: async () => {} });
  assert.match(text(html), /Connected external accounts Nothing connected by this page/);
});

// ------------------------------------------------------------ wording: no false 'connected' claim anywhere

test("the word 'connected' only ever appears in negated or panel-title forms, on every step and mode", () => {
  const allowed = [
    /not connected/gi,
    /Nothing connected by this page/g,
    /Connected external accounts/g,
    /connected accounts/gi,
    /cannot connect/gi,
    /is not connected yet/gi,
    /not connected to this page/gi,
    /signed-in connection to the profile service/gi,
  ];
  const renders = [];
  for (const props of [{}, { onSave: async () => {} }]) {
    for (const step of ["company", "audience", "offerings", "social", "review"]) {
      renders.push(asStep(step, productDraft(), {}, props), asStep(step, EMPTY_DRAFT, { attempted: [step] }, props));
    }
  }
  for (const html of renders) {
    let rest = text(html);
    for (const pattern of allowed) rest = rest.replace(pattern, " ");
    assert.doesNotMatch(rest, /connect/i, rest.slice(Math.max(0, rest.search(/connect/i) - 60), rest.search(/connect/i) + 60));
  }
});

test("sample data is labelled fictional and produces a complete profile", () => {
  const html = asStep("review", productDraft());
  assert.doesNotMatch(html, /gmail|@[a-z]+\.com/i);
  const demo = render();
  assert.match(text(demo), /Fill with fictional sample data/);
  assert.match(text(demo), /Clear the form/);
});

// ------------------------------------------------------------ styling contracts that keep it usable

test("touch targets and wrapping are built into the shared control classes", async () => {
  const fields = await readFile(new URL("components/Fields.tsx", FEATURE_ROOT), "utf8");
  assert.match(fields, /INPUT_CLASS =\s*\n?\s*"[^"]*min-h-\[44px\]/);
  assert.match(fields, /BUTTON_PRIMARY =\s*\n?\s*"[^"]*min-h-\[44px\]/);
  assert.match(fields, /BUTTON_SECONDARY =\s*\n?\s*"[^"]*min-h-\[44px\]/);
  assert.match(fields, /overflow-wrap:anywhere/);
  const page = await readFile(new URL("ClientProfileWizard.tsx", FEATURE_ROOT), "utf8");
  assert.match(page, /lg:grid-cols-\[14rem_minmax\(0,1fr\)\]/, "steps stack below lg and sit beside the form at lg");
});

// ------------------------------------------------------------ AST guards: isolation, no network, no storage, no secrets

async function featureSources() {
  const out = [];
  async function walk(dir) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) await walk(full);
      else if (/\.tsx?$/.test(entry.name)) out.push({ file: path.relative(fileURLToPath(FEATURE_ROOT), full), source: await readFile(full, "utf8") });
    }
  }
  await walk(fileURLToPath(FEATURE_ROOT));
  return out;
}

function scan(file, source) {
  const tree = ts.createSourceFile(file, source, ts.ScriptTarget.ES2020, true, file.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const imports = [];
  const identifiers = new Set();
  const jsxAttributes = [];
  (function visit(node) {
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) {
      if (node.moduleSpecifier) imports.push(node.moduleSpecifier.text);
    }
    if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) imports.push("<dynamic import>");
    if (ts.isIdentifier(node)) identifiers.add(node.text);
    if (ts.isJsxAttribute(node)) jsxAttributes.push({ name: node.name.getText(), value: node.initializer?.getText() ?? "" });
    ts.forEachChild(node, visit);
  })(tree);
  return { imports, identifiers, jsxAttributes };
}

test("guard (AST): the feature imports only react and its own files", async () => {
  const sources = await featureSources();
  assert.ok(sources.length >= 20);
  for (const { file, source } of sources) {
    for (const specifier of scan(file, source).imports) {
      const ok = specifier === "react" || specifier.startsWith("./") || specifier.startsWith("../");
      assert.ok(ok, `${file} imports ${specifier}`);
      if (specifier === "../../../lib/apiBase.ts") {
        assert.equal(file, path.join("lib", "clientProfileApi.ts"), "only the API client may reach the shared API-origin helper");
        continue;
      }
      if (specifier.startsWith("../")) {
        const resolved = path.normalize(path.join(path.dirname(file), specifier));
        assert.ok(!resolved.startsWith(".."), `${file} reaches outside the feature via ${specifier}`);
      }
    }
  }
});

test("guard (AST): no network, storage, cookies, analytics, logging, HTML injection or eval", async () => {
  const forbidden = [
    "XMLHttpRequest", "WebSocket", "EventSource", "sendBeacon", "localStorage", "sessionStorage", "indexedDB",
    "cookie", "console", "posthog", "capturePageview", "dangerouslySetInnerHTML", "innerHTML", "eval", "Function",
    "useQuery", "useMutation", "location", "history", "window", "postMessage", "useSearchParams", "URLSearchParams", "useLocation", "useParams",
  ];
  for (const { file, source } of await featureSources()) {
    const { identifiers } = scan(file, source);
    for (const name of forbidden) assert.ok(!identifiers.has(name), `${file} uses ${name}`);
    // The one network primitive is allowed in exactly one file.
    assert.equal(identifiers.has("fetch"), file === path.join("lib", "clientProfileApi.ts"), `${file}: fetch usage`);
  }
});

test("guard (AST): no identity or connection concepts in identifiers; no password inputs in JSX", async () => {
  const banned = /workspace|tenant|clientId|client_id|ownerId|userId|oauth|accessToken|apiKey|connectAccount|authorize|isConnected|verified/i;
  // The bearer-token SEAM is the one legitimate use: a host-supplied provider threaded to the API client.
  // No form, step or wizard file may name it, and nothing may hold a token value in state.
  const TOKEN_SEAM_FILES = new Set(["lib/clientProfileApi.ts", "hooks/useProfileSession.ts", "ClientProfileOnboardingPage.tsx", "lib/profileSession.ts"]);
  const TOKEN_SEAM_NAMES = /^(getAccessToken|AccessTokenProvider)$/;
  for (const { file, source } of await featureSources()) {
    const { identifiers, jsxAttributes } = scan(file, source);
    const relativeFile = file.replaceAll("\\", "/").replace(/^.*client-crm-profile\//, "");
    for (const name of identifiers) {
      if (TOKEN_SEAM_FILES.has(relativeFile) && TOKEN_SEAM_NAMES.test(name)) continue;
      assert.doesNotMatch(name, banned, `${file}: ${name}`);
    }
    for (const attribute of jsxAttributes) {
      assert.ok(!(attribute.name === "type" && /password/i.test(attribute.value)), `${file} has a password input`);
    }
  }
});

test("guard: the page is not mounted in shared routing, Sidebar or Shell (update MOUNTED_BY when integrating)", async () => {
  const MOUNTED_BY = ["main.tsx"];
  const shared = ["main.tsx", "components/layout/Shell.tsx", "components/layout/Sidebar.tsx"];
  const found = [];
  for (const file of shared) {
    const source = await readFile(new URL(`../../src/${file}`, import.meta.url), "utf8");
    if (/client-crm-profile/.test(source)) found.push(file);
  }
  assert.deepEqual(found, MOUNTED_BY);
});

test("public index exposes the page, the save seam and the draft schema version only", () => {
  assert.deepEqual(Object.keys(featureIndex).sort(), ["CLIENT_PROFILE_DRAFT_SCHEMA_VERSION", "ClientProfileOnboardingPage", "ProfileSaveError"]);
  assert.equal(featureIndex.CLIENT_PROFILE_DRAFT_SCHEMA_VERSION, "client-profile-draft-v0");
  assert.equal(typeof featureIndex.ClientProfileOnboardingPage, "function");
});

test("the initial state helper exposes no persisted or identity fields", () => {
  const keys = Object.keys(initialWizardState()).sort();
  assert.deepEqual(keys, ["announcement", "attempted", "demoReviewedKey", "draft", "focus", "keyCounter", "pending", "save", "savedKey", "step", "touched"]);
});

// ------------------------------------------------------------ review-driven regressions (a11y + truthfulness)

test("live mode says per step which fields the server keeps; demo mode shows no such note", () => {
  const live = { onSave: async () => {} };
  for (const [step, pattern] of [["audience", /Categories stay in this tab only/], ["offerings", /Only the offering names are saved/], ["social", /Only the platform and handle are saved/]]) {
    const html = asStep(step, productDraft(), {}, live);
    assert.match(html, /data-tab-only-note/, step);
    assert.match(text(html), pattern, step);
    assert.doesNotMatch(asStep(step, productDraft()), /data-tab-only-note/, `demo ${step}`);
  }
  assert.doesNotMatch(asStep("company", productDraft(), {}, live), /data-tab-only-note/);
});

test("review: social notes are shown (and marked tab-only when live); success is stated next to Confirm", () => {
  const draft = productDraft({ socialAccounts: [{ key: "s1", platform: "instagram", handle: "example_demo", url: "", notes: "Main shop account" }] });
  assert.match(text(asStep("review", draft, {}, { onSave: async () => {} })), /Notes: Main shop account \(this tab only\)/);
  assert.match(text(asStep("review", draft)), /Notes: Main shop account(?! \(this tab only\))/);
  const key = storedKey(buildPayload(draft));
  const saved = asStep("review", draft, { savedKey: key, save: { status: "saved" } }, { onSave: async () => {} });
  const at = saved.indexOf("data-save-status");
  assert.ok(at > 0 && at < saved.indexOf("data-confirm"), "the success line precedes the Confirm button");
  assert.match(text(saved.slice(at, saved.indexOf("data-confirm"))), /Profile saved\. The details under "Stays in this tab only" were not sent\./);
  const changed = asStep("review", { ...draft, companyName: "Renamed Demo Co" }, { savedKey: key, save: { status: "saved" } }, { onSave: async () => {} });
  assert.doesNotMatch(changed, /data-save-status/, "no success line once the form differs from what was saved");
});

test("a failed save's visible duplicate is hidden from assistive technology; the announcement carries the reason", () => {
  const html = asStep("review", productDraft(), { save: { status: "error", code: "conflict" } }, { onSave: async () => {} });
  assert.match(html, /data-save-error="conflict"[^>]*aria-hidden="true"/);
  const state = wizardReducer(initialWizardState({ draft: productDraft(), step: "review" }), { type: "saveFailed", code: "conflict" });
  assert.match(state.announcement, /changed elsewhere.*Your entries are still here/);
});

test("accessibility details: focusable page heading, 3:1 control borders, required radios, no notes overflowing the gutter", async () => {
  assert.match(asStep("company", EMPTY_DRAFT), /<h1[^>]*id="cp-page-heading"[^>]*tabindex="-1"/);
  const radios = tagsOf(asStep("company", EMPTY_DRAFT), "input", (t) => attr(t, "type") === "radio");
  assert.ok(radios.every((t) => has(t, "required")), "business type is exposed as required to assistive technology");
  const fields = await readFile(new URL("../../src/features/client-crm-profile/components/Fields.tsx", import.meta.url), "utf8");
  assert.match(fields, /INPUT_CLASS =\s*"[^"]*border-zinc-500/);
  assert.doesNotMatch(fields, /INPUT_CLASS =\s*"[^"]*border-zinc-700/);
  const panels = await readFile(new URL("../../src/features/client-crm-profile/components/LoadPanels.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(panels, /sm:mx-6/, "a note must not combine w-full with a side margin");
});
