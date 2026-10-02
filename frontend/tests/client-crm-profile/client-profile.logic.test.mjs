/**
 * Client CRM profile: logic tests (validation, business-type behaviour, payload,
 * wizard state machine, save orchestration). Pure modules only; no DOM.
 * The save function in the runSave tests is a MOCK: no real API exists.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { importFeature } from "./load.mjs";

const contracts = await importFeature("contracts/clientProfileDraft.ts");
const { validateProfile, validateProfileUrl, validateTag, normalizeHandle, stepOfPath } = await importFeature("lib/validateProfile.ts");
const { looksLikeSecret } = await importFeature("lib/secretShape.ts");
const { prepareTags } = await importFeature("lib/tags.ts");
const { buildPayload, payloadKey } = await importFeature("lib/toPayload.ts");
const { runSave } = await importFeature("lib/runSave.ts");
const { storedKey } = await importFeature("lib/toServerBody.ts");
const textLib = await importFeature("lib/text.ts");
const { EMPTY_DRAFT, initialWizardState, wizardReducer, wizardValidation, pendingErrors, isBlank, saveView, stepStatus, demoReviewedNow } = await importFeature("lib/wizardState.ts");
const { buildSampleDraft } = await importFeature("fixtures/sampleProfile.ts");

// ------------------------------------------------------------ builders

const offering = (over = {}) => ({ key: "o1", name: "Item", description: "", delivery: "", availability: "", sku: "", quantity: "", ...over });
const account = (over = {}) => ({ key: "s1", platform: "instagram", handle: "example_demo", url: "", notes: "", ...over });

const productDraft = (over = {}) => ({
  companyName: "Example Demo Co",
  businessType: "product",
  categories: ["Coffee equipment"],
  segments: ["Home baristas"],
  targetMarkets: ["Canada"],
  offerings: [offering({ availability: "in_stock" })],
  socialAccounts: [],
  ...over,
});
const serviceDraft = (type = "service_b2b", over = {}) => ({
  ...productDraft(),
  businessType: type,
  offerings: [offering({ name: "Bookkeeping", delivery: "remote" })],
  ...over,
});
const paths = (draft) => validateProfile(draft).errors.map((error) => error.path);
const messageFor = (draft, path) => validateProfile(draft).errors.find((error) => error.path === path)?.message;

// ------------------------------------------------------------ completeness / missing values

test("an empty draft reports every required item, grouped by step, and is not complete", () => {
  const result = validateProfile(EMPTY_DRAFT);
  assert.equal(result.complete, false);
  assert.deepEqual(
    result.errors.map((error) => error.path),
    ["companyName", "businessType", "segments", "targetMarkets", "offerings"],
  );
  assert.ok(result.errors.every((error) => error.code === "required"));
  assert.deepEqual(result.byStep.company.map((e) => e.path), ["companyName", "businessType"]);
  assert.deepEqual(result.byStep.audience.map((e) => e.path), ["segments", "targetMarkets"], "categories are not stored by the service, so they are optional");
  assert.deepEqual(result.byStep.offerings.map((e) => e.path), ["offerings"]);
  assert.deepEqual(result.byStep.social, [], "social accounts are optional");
  assert.deepEqual(result.byStep.review, []);
});

test("complete product and service profiles validate; social accounts stay optional", () => {
  assert.equal(validateProfile(productDraft()).complete, true);
  for (const type of ["service_b2b", "service_b2c"]) assert.equal(validateProfile(serviceDraft(type)).complete, true, type);
});

test("error messages are specific and tell the person what to do", () => {
  assert.equal(messageFor(EMPTY_DRAFT, "companyName"), "Enter your company name.");
  assert.equal(messageFor(EMPTY_DRAFT, "businessType"), "Choose the business type that fits best.");
  assert.equal(messageFor(EMPTY_DRAFT, "categories"), undefined, "categories are optional");
  assert.equal(messageFor(EMPTY_DRAFT, "offerings"), "Add at least one product or service.");
  assert.equal(messageFor(productDraft({ offerings: [] }), "offerings"), "Add at least one product.");
  assert.equal(messageFor(serviceDraft("service_b2c", { offerings: [] }), "offerings"), "Add at least one service.");
  assert.match(messageFor(productDraft({ segments: [] }), "segments"), /Add at least one entry for customer segments\./);
  assert.match(messageFor(serviceDraft("service_b2b", { segments: [] }), "segments"), /buyer segments/);
});

test("stepOfPath maps every path family to its step", () => {
  assert.equal(stepOfPath("companyName"), "company");
  assert.equal(stepOfPath("businessType"), "company");
  assert.equal(stepOfPath("targetMarkets"), "audience");
  assert.equal(stepOfPath("offerings.2.sku"), "offerings");
  assert.equal(stepOfPath("socialAccounts.0.url"), "social");
});

// ------------------------------------------------------------ company identity

test("company name: length, control characters and credential shapes are rejected", () => {
  assert.equal(messageFor(productDraft({ companyName: "A" }), "companyName"), "The company name must be at least 2 characters.");
  assert.match(messageFor(productDraft({ companyName: "x".repeat(121) }), "companyName"), /120 characters or fewer/);
  assert.match(messageFor(productDraft({ companyName: "Bad\u0007Name" }), "companyName"), /not allowed/);
  assert.match(messageFor(productDraft({ companyName: "password: hunter2" }), "companyName"), /password, token or key/);
  assert.equal(messageFor(productDraft({ companyName: "   Ok Co   " }), "companyName"), undefined, "surrounding spaces are trimmed, not an error");
  assert.equal(messageFor(productDraft({ companyName: "   " }), "companyName"), "Enter your company name.");
});

// ------------------------------------------------------------ business type behaviour

test("service types do not require delivery and ignore inventory fields", () => {
  const draft = serviceDraft("service_b2b", { offerings: [offering({ name: "Audit", quantity: "abc", sku: "!!bad!!" })] });
  assert.deepEqual(paths(draft), [], "delivery is not stored by the service, so it is optional; quantity/SKU are not evaluated for services");
  assert.equal(buildPayload(draft).offerings[0].delivery, undefined, "an unchosen delivery is left out, never sent as an empty string");
});

test("product type validates the optional availability and inventory fields", () => {
  const base = productDraft({ offerings: [offering({ name: "Kettle", availability: "" })] });
  assert.equal(messageFor(base, "offerings.0.availability"), undefined, "availability is not stored by the service, so it is optional");
  assert.equal(buildPayload(base).offerings[0].availability, undefined);
  const withBad = (patch) => productDraft({ offerings: [offering({ name: "Kettle", availability: "in_stock", ...patch })] });
  assert.equal(messageFor(withBad({ quantity: "12" }), "offerings.0.quantity"), undefined);
  assert.equal(messageFor(withBad({ quantity: "" }), "offerings.0.quantity"), undefined, "empty quantity is allowed: not reported");
  for (const bad of ["abc", "-1", "1.5", "1e3", "١٢"]) {
    assert.match(messageFor(withBad({ quantity: bad }), "offerings.0.quantity"), /whole number/, bad);
  }
  assert.match(messageFor(withBad({ quantity: "1000001" }), "offerings.0.quantity"), /1,000,000 or fewer/);
  assert.equal(messageFor(withBad({ sku: "DEMO-01/A" }), "offerings.0.sku"), undefined);
  assert.match(messageFor(withBad({ sku: "bad<sku>" }), "offerings.0.sku"), /letters, numbers/);
});

test("service delivery is not required for a product, and availability is not required for a service", () => {
  assert.equal(messageFor(productDraft(), "offerings.0.delivery"), undefined);
  assert.equal(messageFor(serviceDraft(), "offerings.0.availability"), undefined);
});

test("offering names are required per row and reported by row number", () => {
  const draft = serviceDraft("service_b2c", { offerings: [offering({ name: "Ok", delivery: "remote" }), offering({ key: "o2", name: "", delivery: "hybrid" })] });
  assert.equal(messageFor(draft, "offerings.1.name"), "Enter a name for service 2.");
  assert.equal(messageFor(draft, "offerings.0.name"), undefined);
});

test("two offerings with the same name are refused (the service rejects them), case-insensitively", () => {
  const draft = productDraft({ offerings: [offering({ name: "Kettle" }), offering({ key: "o2", name: " kettle " })] });
  assert.equal(messageFor(draft, "offerings.1.name"), "This is the same name as product 1. Use a different name or remove one.");
  assert.equal(validateProfile(draft).complete, false);
  assert.equal(messageFor(draft, "offerings.0.name"), undefined);
});

test("the form offers every business type and social platform the service accepts, and no more offerings than it allows", () => {
  assert.deepEqual([...contracts.BUSINESS_TYPES], ["service_b2c", "service_b2b", "product", "other"]);
  assert.deepEqual([...contracts.SOCIAL_PLATFORMS].sort(), ["facebook", "instagram", "linkedin", "other", "pinterest", "threads", "tiktok", "x", "youtube"]);
  assert.equal(contracts.LIMITS.maxOfferings, 25);
  assert.ok(contracts.LIMITS.maxSegments <= 25 && contracts.LIMITS.maxTargetMarkets <= 25 && contracts.LIMITS.maxSocialAccounts <= 25);
  const many = productDraft({ offerings: Array.from({ length: 26 }, (_, i) => offering({ key: `o${i}`, name: `Item ${i}` })) });
  assert.ok(paths(many).includes("offerings"), "26 offerings exceed the service limit");
});

test("switching business type keeps what was typed; only the fields that apply are validated and sent", () => {
  const typed = offering({ name: "Kettle", availability: "in_stock", sku: "K-1", quantity: "5", delivery: "" });
  const asProduct = productDraft({ offerings: [typed] });
  assert.equal(validateProfile(asProduct).complete, true);

  const state = wizardReducer(initialWizardState({ draft: asProduct }), { type: "setBusinessType", value: "service_b2b" });
  assert.equal(state.draft.offerings[0].sku, "K-1", "inventory entries are retained");
  assert.equal(state.draft.offerings[0].availability, "in_stock");
  assert.deepEqual(paths(state.draft), [], "a service no longer needs a delivery mode to be complete");
  assert.match(state.announcement, /Your offerings are kept/);

  const back = wizardReducer(state, { type: "setBusinessType", value: "product" });
  assert.equal(validateProfile(back.draft).complete, true, "switching back restores a complete product profile");
  assert.equal(back.draft.offerings[0].quantity, "5");
});

test("segments label follows the business type (B2C, B2B, product)", () => {
  const meta = contracts.BUSINESS_TYPE_META;
  assert.equal(meta.service_b2c.segmentsLabel, "Customer segments");
  assert.equal(meta.service_b2b.segmentsLabel, "Buyer segments");
  assert.equal(meta.product.segmentsLabel, "Customer segments");
  assert.deepEqual(Object.keys(meta), ["service_b2c", "service_b2b", "other", "product"]);
  assert.deepEqual(Object.keys(meta).filter((k) => meta[k].tracksInventory), ["product"]);
  assert.deepEqual([...contracts.BUSINESS_TYPES].sort(), Object.keys(meta).sort(), "every type the service accepts has form copy");
});

// ------------------------------------------------------------ tags

test("tags: each entry is length-checked, credential-checked and limited", () => {
  assert.match(validateTag("a", "Category"), /at least 2 characters/);
  assert.match(validateTag("x".repeat(61), "Category"), /60 characters or fewer/);
  assert.match(validateTag("token=abcdef123456", "Category"), /password, token or key/);
  assert.equal(validateTag("  Coffee   gear ", "Category"), null);
  const many = Array.from({ length: 11 }, (_, i) => `Category ${i}`);
  assert.equal(paths(productDraft({ categories: many })).includes("categories"), true);
  assert.match(messageFor(productDraft({ categories: ["ok fine", "password: abc123"] }), "categories"), /"password: abc123": This looks like a password/);
});

test("prepareTags splits on commas/newlines, de-duplicates and is all-or-nothing", () => {
  const ok = prepareTags("Coffee, tea\nGear ; coffee", ["Books"], "Category", 10);
  assert.deepEqual(ok.accepted, ["Coffee", "tea", "Gear"]);
  assert.equal(ok.error, null);

  const dup = prepareTags("books, Mugs", ["Books"], "Category", 10);
  assert.deepEqual(dup.accepted, ["Mugs"]);
  assert.deepEqual(dup.duplicates, ["books"]);

  assert.match(prepareTags("   ", [], "Category", 10).error, /Type a category first/);
  const invalid = prepareTags("Fine, x", [], "Category", 10);
  assert.deepEqual(invalid.accepted, [], "nothing is added when any piece is invalid");
  assert.match(invalid.error, /at least 2 characters/);
  assert.match(prepareTags("One, Two", ["A1", "B2"], "Category", 3).error, /up to 3 entries/);
});

// ------------------------------------------------------------ secrets

test("credential-shaped text is detected; ordinary business text is not", () => {
  const secrets = [
    "sk-live-abcdefghijklmnop1234",
    "ghp_abcdefghijklmnopqrstuvwxyz0123",
    "xoxb-1234567890-abcdefghij",
    "AKIAABCDEFGHIJKLMNOP",
    "Bearer abcdefghijklmnop.qrstuvw",
    "password: hunter2",
    "api_key=abc123",
    "token = xyz",
    "-----BEGIN PRIVATE KEY-----",
    "a".repeat(40),
  ];
  for (const secret of secrets) assert.equal(looksLikeSecret(secret), true, secret);
  const fine = ["Password manager for small teams", "Token Coffee Roasters", "Secret Garden Books", "Key West Candle Co.", "Home baristas", "Nordics"];
  for (const text of fine) assert.equal(looksLikeSecret(text), false, text);
});

// ------------------------------------------------------------ social accounts

test("social accounts are optional, but each account needs a platform and a handle or link", () => {
  assert.equal(validateProfile(productDraft({ socialAccounts: [] })).complete, true);
  const draft = productDraft({ socialAccounts: [account({ platform: "", handle: "", url: "" })] });
  assert.deepEqual(paths(draft), ["socialAccounts.0.platform", "socialAccounts.0.handle"]);
  assert.equal(messageFor(draft, "socialAccounts.0.handle"), "Enter a handle or a profile link for account 1.");
});

test("handles: a leading @ is normalized; spaces and odd characters are rejected", () => {
  assert.equal(normalizeHandle("  @Shop_Name "), "Shop_Name");
  assert.equal(messageFor(productDraft({ socialAccounts: [account({ handle: "@ok.handle_1" })] }), "socialAccounts.0.handle"), undefined);
  assert.match(messageFor(productDraft({ socialAccounts: [account({ handle: "no-dash" })] }), "socialAccounts.0.handle"), /dots and underscores/, "the service rejects a dash");
  assert.match(messageFor(productDraft({ socialAccounts: [account({ handle: "has space" })] }), "socialAccounts.0.handle"), /no spaces/);
  assert.match(messageFor(productDraft({ socialAccounts: [account({ handle: "bad/handle" })] }), "socialAccounts.0.handle"), /letters, numbers/);
});

test("profile links must be plain https links without credentials or secret query values", () => {
  assert.equal(validateProfileUrl("https://www.instagram.com/example_demo", "instagram"), null);
  assert.equal(validateProfileUrl("https://instagram.com/example_demo?utm_source=x&keyword=shoes", "instagram"), null, "'keyword' is not a secret key");
  assert.match(validateProfileUrl("instagram.com/x", "instagram"), /starts with https/);
  assert.match(validateProfileUrl("http://instagram.com/x", "instagram"), /https/);
  assert.match(validateProfileUrl("javascript:alert(1)", "other"), /https/);
  assert.match(validateProfileUrl("https://user:pass@instagram.com/x", "instagram"), /username or password/);
  assert.match(validateProfileUrl("https://instagram.com/x?access_token=abc", "instagram"), /token, key or session/);
  assert.match(validateProfileUrl("https://instagram.com/x?api_key=abc", "instagram"), /token, key or session/);
  assert.match(validateProfileUrl("https://instagram.com/x?session=abc", "instagram"), /token, key or session/);
  assert.match(validateProfileUrl("https://localhost/x", "other"), /no valid website address/);
  assert.match(validateProfileUrl(`https://example.com/${"a".repeat(300)}`, "other"), /300 characters or fewer/);
});

test("profile link host must match the chosen platform; 'other' accepts any https host", () => {
  assert.match(validateProfileUrl("https://tiktok.com/@x", "instagram"), /does not look like a Instagram address/);
  assert.match(validateProfileUrl("https://evilinstagram.com/x", "instagram"), /does not look/, "suffix tricks are not accepted");
  assert.equal(validateProfileUrl("https://twitter.com/x", "x"), null);
  assert.equal(validateProfileUrl("https://youtu.be/abc", "youtube"), null);
  assert.equal(validateProfileUrl("https://my-shop.example.com/social", "other"), null);
});

test("duplicate platform+handle is flagged on the later account only", () => {
  const draft = productDraft({ socialAccounts: [account({ key: "a", handle: "Shop" }), account({ key: "b", handle: "@shop" })] });
  assert.deepEqual(paths(draft), ["socialAccounts.1.handle"]);
  assert.match(messageFor(draft, "socialAccounts.1.handle"), /same handle as account 1/);
  const differentPlatform = productDraft({ socialAccounts: [account({ key: "a", handle: "shop" }), account({ key: "b", platform: "tiktok", handle: "shop" })] });
  assert.equal(validateProfile(differentPlatform).complete, true);
});

test("notes reject credential shapes and long text", () => {
  assert.match(messageFor(productDraft({ socialAccounts: [account({ notes: "login password: abc123" })] }), "socialAccounts.0.notes"), /password, token or key/);
  assert.match(messageFor(productDraft({ socialAccounts: [account({ notes: "n".repeat(201) })] }), "socialAccounts.0.notes"), /200 characters or fewer/);
});

// ------------------------------------------------------------ payload

test("buildPayload is fail-closed: null unless the whole draft is valid", () => {
  assert.equal(buildPayload(EMPTY_DRAFT), null);
  assert.equal(buildPayload(productDraft({ companyName: "" })), null);
  assert.equal(payloadKey(null), null);
  assert.ok(buildPayload(productDraft()));
});

test("product payload: quantity null (never 0) when unreported, number when given; no service fields", () => {
  const payload = buildPayload(productDraft({ offerings: [offering({ name: "Kettle", availability: "in_stock", sku: " K-1 ", quantity: "" }), offering({ key: "o2", name: "Grinder", availability: "unknown", quantity: "0012" })] }));
  assert.equal(payload.schema_version, "client-profile-draft-v0");
  assert.deepEqual(payload.offerings[0], { name: "Kettle", description: null, availability: "in_stock", sku: "K-1", quantity: null });
  assert.equal(payload.offerings[1].quantity, 12);
  assert.equal("delivery" in payload.offerings[0], false);
});

test("service payload never carries inventory fields, even if they were typed before switching type", () => {
  const draft = serviceDraft("service_b2b", { offerings: [offering({ name: "Audit", delivery: "hybrid", availability: "in_stock", sku: "S-1", quantity: "9" })] });
  const payload = buildPayload(draft);
  assert.deepEqual(payload.offerings[0], { name: "Audit", description: null, delivery: "hybrid" });
  assert.equal(payload.business_type, "service_b2b");
});

test("payload normalizes text and de-duplicates tags case-insensitively", () => {
  const payload = buildPayload(productDraft({ companyName: "  Example   Demo  Co ", categories: ["Coffee", "coffee", " Tea "], targetMarkets: ["Canada"] }));
  assert.equal(payload.company_name, "Example Demo Co");
  assert.deepEqual(payload.categories, ["Coffee", "Tea"]);
});

test("payload social accounts can only be 'not_connected' and hold plain details", () => {
  const payload = buildPayload(productDraft({ socialAccounts: [account({ handle: "@Shop", url: "https://instagram.com/shop", notes: " hi " }), account({ key: "s2", platform: "other", handle: "", url: "https://example.com/p" })] }));
  assert.deepEqual(payload.social_accounts[0], { platform: "instagram", handle: "Shop", url: "https://instagram.com/shop", notes: "hi", link_status: "not_connected" });
  assert.equal(payload.social_accounts[1].handle, null);
  assert.ok(payload.social_accounts.every((item) => item.link_status === "not_connected"));
});

test("payload has no identity, tenant, connection or credential keys anywhere", () => {
  const payload = buildPayload(productDraft({ socialAccounts: [account()] }));
  const keys = [];
  (function walk(value) {
    if (Array.isArray(value)) value.forEach(walk);
    else if (value && typeof value === "object") for (const [key, inner] of Object.entries(value)) { keys.push(key); walk(inner); }
  })(payload);
  const banned = /workspace|tenant|client_?id|owner|user_?id|account_?id|token|secret|password|api_?key|oauth|verified|connected$/i;
  assert.deepEqual(keys.filter((key) => banned.test(key)), []);
});

// ------------------------------------------------------------ wizard state machine

const run = (state, ...actions) => actions.reduce(wizardReducer, state);

test("Next is blocked with a focus request and announcement while the step has problems", () => {
  const blocked = run(initialWizardState(), { type: "next" });
  assert.equal(blocked.step, "company");
  assert.deepEqual(blocked.attempted, ["company"]);
  assert.equal(blocked.focus.target, "summary");
  assert.equal(blocked.announcement, "", "focus moves to the problem list, so no second live announcement repeats it");

  const filled = run(blocked, { type: "setCompanyName", value: "Example Demo Co" }, { type: "setBusinessType", value: "product" }, { type: "next" });
  assert.equal(filled.step, "audience");
  assert.equal(filled.focus.target, "heading");
  assert.match(filled.announcement, /Step 2 of 5: Categories, segments and target markets\./);
});

test("Back and step navigation are never blocked; goto can target a field", () => {
  const at = run(initialWizardState({ step: "offerings" }), { type: "back" });
  assert.equal(at.step, "audience");
  const jumped = run(at, { type: "goto", step: "social" });
  assert.equal(jumped.step, "social");
  const toField = run(jumped, { type: "goto", step: "offerings", path: "offerings.0.name" });
  assert.deepEqual([toField.step, toField.focus.target, toField.focus.path], ["offerings", "field", "offerings.0.name"]);
  assert.equal(run(initialWizardState(), { type: "back" }).step, "company", "Back at the first step stays put");
});

test("focus requests are distinct each time (nonce increments)", () => {
  const first = run(initialWizardState(), { type: "next" });
  const second = run(first, { type: "next" });
  assert.equal(second.focus.nonce, first.focus.nonce + 1);
});

test("tags: adding de-duplicates, respects the limit and announces; removing announces", () => {
  let state = run(initialWizardState(), { type: "addTags", field: "categories", tags: ["Coffee", "Tea"] });
  assert.deepEqual(state.draft.categories, ["Coffee", "Tea"]);
  assert.match(state.announcement, /Added 2 categories\. 2 categories in the list\./);
  const same = run(state, { type: "addTags", field: "categories", tags: ["coffee"] });
  assert.equal(same, state, "adding only duplicates changes nothing");
  state = run(state, { type: "removeTag", field: "categories", index: 0 });
  assert.deepEqual(state.draft.categories, ["Tea"]);
  assert.match(state.announcement, /Removed category Coffee\. 1 category left\./);
  assert.equal(run(state, { type: "removeTag", field: "categories", index: 9 }), state);
  const capped = run(initialWizardState(), { type: "addTags", field: "categories", tags: Array.from({ length: 15 }, (_, i) => `Cat ${i}`) });
  assert.equal(capped.draft.categories.length, 10);
});

test("offerings and accounts: stable unique keys, focus on the new row, edits and removals by key", () => {
  let state = run(initialWizardState(), { type: "addOffering" }, { type: "addOffering" });
  const [a, b] = state.draft.offerings.map((o) => o.key);
  assert.notEqual(a, b);
  assert.equal(state.focus.path, "offerings.1.name");
  state = run(state, { type: "updateOffering", key: a, patch: { name: "Kettle" } });
  assert.equal(state.draft.offerings[0].name, "Kettle");
  state = run(state, { type: "removeOffering", key: a }, { type: "addOffering" });
  const keys = state.draft.offerings.map((o) => o.key);
  assert.equal(new Set(keys).size, keys.length, "keys are never reused after a removal");
  assert.equal(run(state, { type: "removeOffering", key: "missing" }), state);

  let social = run(initialWizardState(), { type: "addSocial" });
  assert.equal(social.focus.path, "socialAccounts.0.platform");
  assert.match(social.announcement, /plain detail and is not connected/);
  assert.doesNotMatch(social.announcement, /saved/i, "demo mode must never say a detail is saved");
  social = run(social, { type: "removeSocial", key: social.draft.socialAccounts[0].key });
  assert.equal(social.draft.socialAccounts.length, 0);
  assert.equal(social.focus.path, "socialAccounts-add", "focus falls back to the Add button when the list empties");
});

test("removing a row clears row-level 'touched' marks so errors cannot jump to the wrong row", () => {
  let state = run(initialWizardState(), { type: "addOffering" }, { type: "addOffering" }, { type: "blur", path: "offerings.1.name" }, { type: "blur", path: "companyName" });
  state = run(state, { type: "removeOffering", key: state.draft.offerings[0].key });
  assert.deepEqual(state.touched, ["companyName"]);
});

test("text typed into a tag box but not added is flagged, never silently dropped", () => {
  const withText = wizardReducer(initialWizardState({ draft: { ...EMPTY_DRAFT, categories: ["Tea"] } }), { type: "setPending", field: "categories", value: "Coffee" });
  assert.equal(withText.pending.categories, "Coffee");
  assert.deepEqual(pendingErrors(withText.pending).map((e) => e.path), ["categories"]);
  assert.match(pendingErrors(withText.pending)[0].message, /text in the category box that has not been added\. Choose Add category, or clear the box\./);
  assert.doesNotMatch(JSON.stringify(pendingErrors({ categories: "password: hunter2", segments: "", targetMarkets: "" })), /hunter2/, "the typed text is never echoed into messages");

  const v = wizardValidation(withText);
  assert.equal(v.complete, false);
  assert.equal(v.byStep.audience[0].path, "categories", "the pending message comes first for its field");
  assert.equal(wizardValidation({ draft: productDraft(), pending: { categories: "", segments: "  ", targetMarkets: "" } }).complete, true);

  // Next is blocked even though the list already has an entry (the silent-loss case)
  const audience = initialWizardState({ step: "audience", draft: productDraft(), pending: { categories: "Extra", segments: "", targetMarkets: "" } });
  const blocked = wizardReducer(audience, { type: "next" });
  assert.equal(blocked.step, "audience");
  assert.equal(blocked.focus.target, "summary");
  // adding clears it; the typed text is kept while navigating away and back
  const added = wizardReducer(audience, { type: "addTags", field: "categories", tags: ["Extra"] });
  assert.equal(added.pending.categories, "");
  assert.equal(wizardReducer(wizardReducer(audience, { type: "goto", step: "social" }), { type: "goto", step: "audience" }).pending.categories, "Extra");
  // and a complete draft with leftover text cannot be confirmed
  const review = wizardReducer(initialWizardState({ step: "review", draft: productDraft(), pending: { categories: "x1", segments: "", targetMarkets: "" } }), { type: "confirmAttempt" });
  assert.deepEqual(review.attempted, ["review"]);
});

test("isBlank tells an untouched form from one with work in it", () => {
  assert.equal(isBlank(initialWizardState()), true);
  assert.equal(isBlank(wizardReducer(initialWizardState(), { type: "setCompanyName", value: "  " })), true, "whitespace is not work");
  assert.equal(isBlank(wizardReducer(initialWizardState(), { type: "setCompanyName", value: "Ex" })), false);
  assert.equal(isBlank(wizardReducer(initialWizardState(), { type: "setPending", field: "segments", value: "abc" })), false);
  assert.equal(isBlank(wizardReducer(initialWizardState(), { type: "addSocial" })), false);
});

test("confirm attempt on an incomplete profile focuses the missing-information summary; a complete one is a no-op", () => {
  const blocked = run(initialWizardState({ step: "review" }), { type: "confirmAttempt" });
  assert.deepEqual(blocked.attempted, ["review"]);
  assert.equal(blocked.focus.target, "summary");
  assert.match(blocked.announcement, /Cannot confirm yet: 5 items need attention/);
  const complete = initialWizardState({ draft: productDraft(), step: "review" });
  assert.equal(run(complete, { type: "confirmAttempt" }), complete);
});

test("sample data is fictional, complete and clearly labelled; clear resets to an empty form", () => {
  const loaded = run(initialWizardState(), { type: "loadSample" });
  assert.equal(validateProfile(loaded.draft).complete, true);
  assert.match(loaded.draft.companyName, /\(sample\)/);
  assert.match(loaded.announcement, /not real client information/);
  const payload = buildPayload(loaded.draft);
  assert.doesNotMatch(JSON.stringify(payload), /https?:\/\/(?!example\.)/, "no real-looking links in the sample");
  const cleared = run(loaded, { type: "clear" });
  assert.deepEqual(cleared.draft, EMPTY_DRAFT);
  assert.equal(cleared.step, "company");
  const sample = buildSampleDraft((prefix, index) => `${prefix}-${index}`);
  assert.equal(sample.socialAccounts[0].notes, "Fictional sample handle. Not connected.");
});

test("step status: complete / needs attention / not complete / optional", () => {
  const empty = initialWizardState();
  const v = validateProfile(empty.draft);
  assert.equal(stepStatus("company", v, empty), "incomplete");
  assert.equal(stepStatus("social", v, empty), "optional");
  const attempted = run(empty, { type: "next" });
  assert.equal(stepStatus("company", validateProfile(attempted.draft), attempted), "needs_attention");
  const full = initialWizardState({ draft: productDraft() });
  const fv = validateProfile(full.draft);
  assert.deepEqual(["company", "audience", "offerings", "review"].map((s) => stepStatus(s, fv, full)), ["complete", "complete", "complete", "complete"]);
});

// ------------------------------------------------------------ saved vs demo, honesty of "saved"

test("without persistence the profile is never described as saved, even after a demo confirmation", () => {
  const base = initialWizardState({ draft: productDraft(), step: "review" });
  assert.equal(saveView(base, false), "demo");
  const key = payloadKey(buildPayload(base.draft));
  const reviewed = run(base, { type: "demoReviewed", key });
  assert.equal(saveView(reviewed, false), "demo");
  assert.equal(demoReviewedNow(reviewed), true);
  const edited = run(reviewed, { type: "setCompanyName", value: "Another Demo Co" });
  assert.equal(demoReviewedNow(edited), false, "an edit invalidates the demo confirmation");
});

test("with persistence, 'saved' holds only while the form still equals what was saved", () => {
  let state = initialWizardState({ draft: productDraft(), step: "review" });
  assert.equal(saveView(state, true), "unsaved");
  state = run(state, { type: "saveStarted" });
  assert.equal(saveView(state, true), "saving");
  state = run(state, { type: "saveSucceeded", key: storedKey(buildPayload(state.draft)) });
  assert.equal(saveView(state, true), "saved");
  state = run(state, { type: "setCompanyName", value: "Renamed Demo Co" });
  assert.equal(saveView(state, true), "changed_since_saved");
  state = run(state, { type: "setCompanyName", value: "Example Demo Co" });
  assert.equal(saveView(state, true), "saved", "reverting the edit matches the saved profile again");
  state = run(state, { type: "addTags", field: "categories", tags: ["Tea"] });
  assert.equal(saveView(state, true), "saved", "a tab-only field the service does not store never reads as unsaved");
  state = run(state, { type: "saveFailed", code: "unavailable" });
  assert.equal(saveView(state, true), "error");
  assert.match(state.announcement, /Your entries are still here/);
});

// ------------------------------------------------------------ save orchestration (MOCKED persistence)

test("runSave: saved only after the promise resolves, with the payload key", async () => {
  const payload = buildPayload(productDraft());
  const seen = [];
  const calls = [];
  await runSave(async (received) => { calls.push(received); }, payload, (action) => seen.push(action));
  assert.deepEqual(seen.map((a) => a.type), ["saveStarted", "saveSucceeded"]);
  assert.equal(seen[1].key, storedKey(payload));
  assert.deepEqual(calls, [payload]);
});

test("runSave: typed failures become codes; raw error text is never surfaced", async () => {
  const payload = buildPayload(productDraft());
  for (const code of ["unauthenticated", "forbidden", "validation", "conflict", "unavailable"]) {
    const seen = [];
    await runSave(async () => { throw new contracts.ProfileSaveError(code); }, payload, (a) => seen.push(a));
    assert.deepEqual(seen.map((a) => a.type), ["saveStarted", "saveFailed"]);
    assert.equal(seen[1].code, code);
  }
  const seen = [];
  await runSave(async () => { throw new Error("SQL error near 'Example Demo Co' token=abc123"); }, payload, (a) => seen.push(a));
  assert.equal(seen[1].code, "unknown");
  assert.doesNotMatch(JSON.stringify(seen), /SQL|abc123|Example Demo/);
});

test("duplicate detection is locale-independent, like the service's Python lower()", () => {
  const { dedupeCaseInsensitive } = textLib;
  const original = String.prototype.toLocaleLowerCase;
  // A Turkish-locale environment lowercases "I" to a dotless i; the service never does.
  String.prototype.toLocaleLowerCase = function () { return this.replace(/I/g, "\u0131").toLowerCase(); };
  try {
    assert.deepEqual(dedupeCaseInsensitive(["INDEX", "index"]), ["INDEX"]);
  } finally {
    String.prototype.toLocaleLowerCase = original;
  }
});
