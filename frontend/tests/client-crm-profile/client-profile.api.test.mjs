/**
 * Client profile <-> /api/organization/client-profile.
 *
 * `fetch` is MOCKED in every test: the backend endpoint is not in this repository,
 * so nothing here exercises a real server. What is proven is how the client behaves
 * for each status the server may send (read, create, update, 401/403/404/409/503,
 * malformed replies, network failure), that identity is never sent or chosen
 * client-side, and that "saved" is claimed only after a trustworthy 2xx.
 *
 * The hook itself (useReducer + useEffect) has no DOM test environment in this repo;
 * its logic lives in pure functions (runLoad, makeSave, sessionReducer) tested here,
 * and its effect wiring is checked in a real browser separately (not part of this suite).
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { importFeature } from "./load.mjs";

const api = await importFeature("lib/clientProfileApi.ts");
const { parseServerProfile } = await importFeature("lib/serverProfile.ts");
const { buildPayload } = await importFeature("lib/toPayload.ts");
const { INITIAL_SESSION, makeSave, runLoad, sessionReducer } = await importFeature("lib/profileSession.ts");
const { EMPTY_DRAFT, initialWizardState } = await importFeature("lib/wizardState.ts");
const { ProfileSaveError, PROFILE_ERROR_CODES } = await importFeature("contracts/clientProfileDraft.ts");
const { LOAD_ERROR_TEXT, SAVE_ERROR_TEXT } = await importFeature("lib/errorCopy.ts");
const Page = (await importFeature("ClientProfileOnboardingPage.tsx")).default;

// ----------------------------------------------------------------- builders

const offering = (over = {}) => ({ key: "o1", name: "Kettle", description: "", delivery: "", availability: "in_stock", sku: "K-1", quantity: "5", ...over });
const productDraft = (over = {}) => ({
  companyName: "Example Demo Co", businessType: "product", categories: ["Coffee equipment"], segments: ["Home baristas"],
  targetMarkets: ["Canada"], offerings: [offering()], socialAccounts: [{ key: "s1", platform: "instagram", handle: "example_demo", url: "", notes: "" }], ...over,
});
const serviceDraft = () => productDraft({ businessType: "service_b2b", offerings: [offering({ name: "Audit", delivery: "remote", availability: "", sku: "", quantity: "" })] });
const payload = (draft = productDraft()) => buildPayload(draft);

/** Records every call; each handler returns a Response-like object or throws. */
function mockFetch(handler) {
  const calls = [];
  const fn = async (input, init = {}) => {
    calls.push({ url: input, ...init });
    return handler(calls.length, input, init);
  };
  fn.calls = calls;
  return fn;
}
const reply = (status, body, { raw } = {}) => ({
  status,
  ok: status >= 200 && status < 300,
  text: async () => (raw !== undefined ? raw : body === undefined ? "" : JSON.stringify(body)),
});

// ----------------------------------------------------------------- request shape: same-origin, no identity

test("GET: same-origin credentials, one fixed URL with no query, no body, no identity headers", async () => {
  const fetchImpl = mockFetch(() => reply(200, payload()));
  await api.fetchClientProfile({ fetchImpl, baseUrl: "" });
  assert.equal(fetchImpl.calls.length, 1);
  const call = fetchImpl.calls[0];
  assert.equal(call.url, "/api/organization/client-profile");
  assert.equal(call.method, "GET");
  assert.equal(call.credentials, "same-origin");
  assert.equal(call.body, undefined);
  assert.deepEqual(Object.keys(call.headers), ["Accept"], "no Authorization, cookie or tenant headers are set by the client");
  assert.doesNotMatch(call.url, /[?#]|workspace|tenant|client_?id/i);
});

test("POST and PATCH send the profile as JSON with same-origin credentials and nothing identifying", async () => {
  for (const [mode, method] of [["create", "POST"], ["update", "PATCH"]]) {
    const fetchImpl = mockFetch(() => reply(200, payload()));
    await api.saveClientProfile(mode, payload(), { fetchImpl, baseUrl: "" });
    const call = fetchImpl.calls[0];
    assert.equal(call.method, method);
    assert.equal(call.credentials, "same-origin");
    assert.equal(call.url, "/api/organization/client-profile");
    assert.deepEqual(Object.keys(call.headers).sort(), ["Accept", "Content-Type"]);
    assert.equal(call.headers["Content-Type"], "application/json");
    assert.deepEqual(JSON.parse(call.body), payload());
    const keys = [];
    (function walk(value) { if (Array.isArray(value)) value.forEach(walk); else if (value && typeof value === "object") for (const [k, v] of Object.entries(value)) { keys.push(k); walk(v); } })(JSON.parse(call.body));
    assert.deepEqual(keys.filter((k) => /workspace|tenant|client_?id|owner|user_?id|token|password/i.test(k)), []);
  }
});

test("the shared API-origin helper decides the base URL; credentials stay same-origin either way", async () => {
  const fetchImpl = mockFetch(() => reply(404));
  await api.fetchClientProfile({ fetchImpl, baseUrl: "https://api.example.test" });
  assert.equal(fetchImpl.calls[0].url, "https://api.example.test/api/organization/client-profile");
  assert.equal(fetchImpl.calls[0].credentials, "same-origin");
});

// ----------------------------------------------------------------- read (GET)

test("successful read: a valid profile becomes the form draft, and a second build yields the same payload", async () => {
  for (const draft of [productDraft(), serviceDraft()]) {
    const sent = payload(draft);
    const result = await api.fetchClientProfile({ fetchImpl: mockFetch(() => reply(200, sent)) });
    assert.equal(result.kind, "ok");
    assert.equal(result.draft.companyName, "Example Demo Co");
    assert.deepEqual(buildPayload(result.draft), sent, "server -> draft -> payload is lossless");
  }
});

test("read: server extras such as a workspace identifier are ignored and never reach the draft", async () => {
  const body = { ...payload(), workspace_id: "ws-from-server", tenant: "t-1", owner_id: "o-1" };
  const result = await api.fetchClientProfile({ fetchImpl: mockFetch(() => reply(200, body)) });
  assert.equal(result.kind, "ok");
  assert.doesNotMatch(JSON.stringify(result), /ws-from-server|t-1|o-1|workspace|tenant/);
});

test("read: 404 is the normal 'no saved profile yet' state, not an error", async () => {
  assert.deepEqual(await api.fetchClientProfile({ fetchImpl: mockFetch(() => reply(404, { detail: "Not Found" })) }), { kind: "not_found" });
});

test("read: 401, 403, 409, 503, 400, 500 each map to their own code", async () => {
  const expected = { 401: "unauthenticated", 403: "forbidden", 409: "conflict", 503: "unavailable", 400: "validation", 422: "validation", 500: "unknown", 502: "unknown", 429: "unknown" };
  for (const [status, code] of Object.entries(expected)) {
    const result = await api.fetchClientProfile({ fetchImpl: mockFetch(() => reply(Number(status), { detail: "SECRET-SERVER-TEXT" })) });
    assert.deepEqual(result, { kind: "error", code }, status);
    assert.doesNotMatch(JSON.stringify(result), /SECRET-SERVER-TEXT/, "server text is never surfaced");
  }
});

test("read: a network failure is its own code; an aborted request reports nothing", async () => {
  assert.deepEqual(await api.fetchClientProfile({ fetchImpl: mockFetch(() => { throw new TypeError("Failed to fetch"); }) }), { kind: "error", code: "network" });
  const controller = new AbortController();
  const fetchImpl = mockFetch(() => { controller.abort(); throw new DOMException("aborted", "AbortError"); });
  assert.deepEqual(await api.fetchClientProfile({ fetchImpl, signal: controller.signal }), { kind: "aborted" });
});

test("read: replies that are not a valid profile are malformed_response, never a profile or an empty form", async () => {
  const good = payload();
  const bad = [
    reply(200, undefined, { raw: "<html>Please sign in</html>" }),       // login page after a redirect
    reply(200, undefined, { raw: "" }),                                    // empty
    reply(200, undefined, { raw: "{not json" }),
    reply(200, undefined, { raw: "x".repeat(api.MAX_RESPONSE_CHARS + 1) }),
    reply(200, [good]),
    reply(200, { ...good, schema_version: "client-profile-draft-v9" }),
    reply(200, { ...good, business_type: "marketplace" }),
    reply(200, { ...good, company_name: 12 }),
    reply(200, { ...good, categories: "Coffee" }),
    reply(200, { ...good, categories: Array.from({ length: 11 }, (_, i) => `c${i}`) }),
    reply(200, { ...good, offerings: [{ name: "Kettle", description: null, availability: "teleported", sku: null, quantity: null }] }),
    reply(200, { ...good, offerings: [{ name: "Kettle", description: null, availability: "in_stock", sku: null, quantity: -1 }] }),
    reply(200, { ...good, offerings: [{ name: "Kettle", description: null, availability: "in_stock", sku: null, quantity: 1.5 }] }),
    reply(200, { ...good, social_accounts: [{ platform: "instagram", handle: "x", url: null, notes: null, link_status: "connected" }] }),
    reply(200, { ...good, social_accounts: [{ platform: "instagram", handle: "x", url: null, notes: null }] }),
    reply(200, { ...good, social_accounts: [{ platform: "myspace", handle: "x", url: null, notes: null, link_status: "not_connected" }] }),
    reply(204),                                                            // a GET with nothing to show
    reply(202, good),
  ];
  for (const response of bad) {
    assert.deepEqual(await api.fetchClientProfile({ fetchImpl: mockFetch(() => response) }), { kind: "error", code: "malformed_response" }, `${response.status}`);
  }
});

test("read: a server that claims an account is connected is refused, so the UI can never show 'connected'", () => {
  const body = { ...payload(), social_accounts: [{ platform: "instagram", handle: "x", url: null, notes: null, link_status: "connected" }] };
  assert.equal(parseServerProfile(body), null);
});

// ----------------------------------------------------------------- save (POST / PATCH)

test("save: 200 and 201 with a valid profile, and 204, are the only successes", async () => {
  for (const response of [reply(200, payload()), reply(201, payload()), reply(204)]) {
    await api.saveClientProfile("create", payload(), { fetchImpl: mockFetch(() => response) });
  }
});

test("save: each failure status throws its own ProfileSaveError code and leaks no server text", async () => {
  const expected = { 401: "unauthenticated", 403: "forbidden", 404: "not_found", 409: "conflict", 503: "unavailable", 400: "validation", 422: "validation", 500: "unknown" };
  for (const mode of ["create", "update"]) {
    for (const [status, code] of Object.entries(expected)) {
      await assert.rejects(
        api.saveClientProfile(mode, payload(), { fetchImpl: mockFetch(() => reply(Number(status), { detail: "SQL error: Example Demo Co" })) }),
        (error) => error instanceof ProfileSaveError && error.code === code && !/SQL|Example/.test(error.message),
        `${mode} ${status}`,
      );
    }
  }
});

test("save: a network failure is 'network'; a 2xx the page cannot trust is 'malformed_response', never a success", async () => {
  await assert.rejects(api.saveClientProfile("update", payload(), { fetchImpl: mockFetch(() => { throw new TypeError("Failed to fetch"); }) }), (e) => e.code === "network");
  const untrusted = [
    reply(200, undefined, { raw: "<html>login</html>" }),
    reply(200, undefined, { raw: "" }),
    reply(200, { ok: true }),
    reply(201, { ...payload(), schema_version: "other" }),
    reply(202, payload()),
    reply(205),
  ];
  for (const response of untrusted) {
    await assert.rejects(api.saveClientProfile("create", payload(), { fetchImpl: mockFetch(() => response) }), (e) => e instanceof ProfileSaveError && e.code === "malformed_response", `${response.status}`);
  }
});

test("save: an aborted request is never a success", async () => {
  const controller = new AbortController();
  const fetchImpl = mockFetch(() => { controller.abort(); throw new DOMException("aborted", "AbortError"); });
  await assert.rejects(api.saveClientProfile("update", payload(), { fetchImpl, signal: controller.signal }), (e) => e instanceof ProfileSaveError && e.code === "network");
});

test("every failure code has distinct load and save wording", () => {
  assert.deepEqual([...PROFILE_ERROR_CODES].sort(), Object.keys(SAVE_ERROR_TEXT).sort());
  assert.equal(new Set(Object.values(SAVE_ERROR_TEXT)).size, PROFILE_ERROR_CODES.length);
  assert.equal(new Set(Object.values(LOAD_ERROR_TEXT)).size, PROFILE_ERROR_CODES.length);
});

// ----------------------------------------------------------------- session: load -> create or update

test("runLoad: existing profile -> update mode; 404 -> create mode with an empty draft; failures keep their code", async () => {
  const run = async (response) => {
    const seen = [];
    await runLoad({ fetchImpl: mockFetch(() => response) }, (action) => seen.push(action));
    return seen.reduce(sessionReducer, INITIAL_SESSION);
  };
  const existing = await run(reply(200, payload()));
  assert.deepEqual([existing.phase, existing.mode, existing.version], ["ready", "update", 1]);
  assert.equal(existing.draft.companyName, "Example Demo Co");
  const none = await run(reply(404));
  assert.deepEqual([none.phase, none.mode, none.draft], ["ready", "create", EMPTY_DRAFT]);
  for (const [status, code] of [[401, "unauthenticated"], [403, "forbidden"], [409, "conflict"], [503, "unavailable"]]) {
    const failed = await run(reply(status));
    assert.deepEqual([failed.phase, failed.code], ["load_failed", code]);
  }
  const malformed = await run(reply(200, { nope: 1 }));
  assert.deepEqual([malformed.phase, malformed.code], ["load_failed", "malformed_response"]);
  const network = await (async () => { const seen = []; await runLoad({ fetchImpl: mockFetch(() => { throw new TypeError("x"); }) }, (a) => seen.push(a)); return seen.reduce(sessionReducer, INITIAL_SESSION); })();
  assert.equal(network.code, "network");
});

test("runLoad: an aborted load changes nothing after loadStarted (no late state from a stale request)", async () => {
  const controller = new AbortController();
  const seen = [];
  await runLoad({ fetchImpl: mockFetch(() => { controller.abort(); throw new DOMException("a", "AbortError"); }), signal: controller.signal }, (a) => seen.push(a));
  assert.deepEqual(seen.map((a) => a.type), ["loadStarted"]);
});

test("makeSave: POST while no profile exists, PATCH after a successful create; failures never flip the mode", async () => {
  let session = sessionReducer(sessionReducer(INITIAL_SESSION, { type: "loadStarted" }), { type: "loadedNone" });
  const dispatch = (action) => { session = sessionReducer(session, action); };
  const outcomes = [reply(503), reply(201, payload()), reply(200, payload()), reply(409)];
  const fetchImpl = mockFetch((n) => outcomes[n - 1]);
  const save = makeSave(() => session, dispatch, { fetchImpl });

  await assert.rejects(save(payload()), (e) => e.code === "unavailable");
  assert.equal(session.mode, "create", "a failed create is still a create");
  await save(payload());
  assert.equal(session.mode, "update");
  await save(payload());
  await assert.rejects(save(payload()), (e) => e.code === "conflict");
  assert.deepEqual(fetchImpl.calls.map((c) => c.method), ["POST", "POST", "PATCH", "PATCH"]);
  assert.equal(session.version, 1, "saving never remounts or resets the form");
});

test("makeSave refuses to run before a profile state is known", async () => {
  const save = makeSave(() => INITIAL_SESSION, () => {}, { fetchImpl: mockFetch(() => reply(200, payload())) });
  await assert.rejects(save(payload()), /profile_not_loaded/);
});

// ----------------------------------------------------------------- container component states (SSR)

const render = (props) => renderToStaticMarkup(createElement(Page, props));
const text = (html) => html.replace(/<[^>]+>/g, " ").replace(/&quot;/g, '"').replace(/&#x27;/g, "'").replace(/&amp;/g, "&").replace(/\s+/g, " ");
const loadedSession = (over = {}) => ({ version: 1, phase: "ready", mode: "update", draft: productDraft(), ...over });

test("loading: a polite busy status, no form and no fields", () => {
  const html = render({ initialSession: INITIAL_SESSION });
  assert.match(html, /role="status"[^>]*aria-busy="true"|aria-busy="true"[^>]*role="status"/);
  assert.match(text(html), /Loading your saved profile/);
  assert.doesNotMatch(html, /<form|<input|<select|<textarea/);
});

test("load failure: every code shows its own alert and a retry, never the form or any profile data", () => {
  const messages = new Set();
  for (const code of PROFILE_ERROR_CODES.filter((c) => c !== "not_found")) {
    const html = render({ initialSession: { version: 0, phase: "load_failed", code } });
    assert.match(html, new RegExp(`data-load-error="${code}"`));
    assert.match(html, /role="alert"/);
    assert.match(text(html), /Your saved profile could not be loaded/);
    assert.match(text(html), /Try again/);
    assert.match(text(html), /Nothing was changed/);
    assert.doesNotMatch(html, /<form|<input|<select|<textarea|Example Demo Co/);
    messages.add(text(html.match(/role="alert".*?<\/div>/s)[0]));
  }
  assert.equal(messages.size, PROFILE_ERROR_CODES.length - 1, "401, 403, 409, 503, malformed, network, ... read differently");
  assert.match(text(render({ initialSession: { version: 0, phase: "load_failed", code: "unauthenticated" } })), /not signed in/);
  assert.match(text(render({ initialSession: { version: 0, phase: "load_failed", code: "forbidden" } })), /not allowed to view/);
  assert.match(text(render({ initialSession: { version: 0, phase: "load_failed", code: "unavailable" } })), /unavailable right now/);
});

test("load failure: the retry control is a real button and the heading can receive focus", () => {
  const html = render({ initialSession: { version: 0, phase: "load_failed", code: "network" } });
  assert.match(html, /<button type="button"[^>]*>Try again<\/button>/);
  assert.match(html, /<h2[^>]*tabindex="-1"/i);
});

test("first visit (404): a 'no saved profile' note, an empty live wizard, no demo or sample controls", () => {
  const html = render({ initialSession: { version: 1, phase: "ready", mode: "create", draft: EMPTY_DRAFT } });
  assert.match(html, /data-no-saved-profile/);
  assert.match(html, /data-mode="persistent"/);
  assert.doesNotMatch(html, /data-mode="demo"|Fill with fictional sample data|Clear the form/);
  assert.doesNotMatch(text(html), /Demo mode|fictional/i);
});

test("existing profile: the server draft prefills the form and nothing claims it was just saved", () => {
  const html = render({ initialSession: loadedSession(), initialState: { step: "review" } });
  assert.match(html, /data-save-view="unsaved"/, "loaded-but-unsaved-by-this-session is not 'saved'");
  assert.match(text(html), /Example Demo Co/);
  assert.doesNotMatch(text(html), /Profile saved|Reviewed in demo mode/);
  assert.match(text(html), /Confirm and save profile/);
  const company = render({ initialSession: loadedSession() });
  assert.match(company, /name="companyName"[^>]*value="Example Demo Co"|value="Example Demo Co"[^>]*name="companyName"/);
});

test("demo source: labelled fictional, not observed, not saved, not connected; sample tools only here", () => {
  const html = render({ source: "demo" });
  assert.match(html, /data-mode="demo"/);
  assert.match(text(html), /Demo mode\. Nothing is saved or sent\./);
  assert.match(text(html), /fictional demo data: it is not observed, not saved and not connected/);
  assert.match(text(html), /Fill with fictional sample data/);
  assert.doesNotMatch(text(html), /Loading your saved profile|could not be loaded/);
  const review = render({ source: "demo", initialState: { step: "review", draft: productDraft() } });
  assert.match(text(review), /Demo only: not saved/);
  assert.match(text(review), /Confirm review \(demo, not saved\)/);
  assert.doesNotMatch(text(review), /Profile saved|Confirm and save profile/);
});

test("the mode is chosen by the mounting code, not by the URL: the page reads no URL or storage state", async () => {
  // `source` is a prop; with no prop the live, server-backed path is used.
  assert.match(render({ initialSession: loadedSession() }), /data-mode="persistent"/);
  assert.match(render({ source: "demo" }), /data-mode="demo"/);
});

test("no workspace, tenant or account selector exists in any state or step", () => {
  const states = [
    { initialSession: INITIAL_SESSION },
    { initialSession: { version: 0, phase: "load_failed", code: "forbidden" } },
    { source: "demo" },
    ...["company", "audience", "offerings", "social", "review"].map((step) => ({ initialSession: loadedSession(), initialState: { step } })),
    ...["company", "audience", "offerings", "social", "review"].map((step) => ({ source: "demo", initialState: { step, draft: productDraft() } })),
  ];
  for (const props of states) {
    const html = render(props);
    const controls = html.match(/<(input|select|textarea|button)\b[^>]*>/g) ?? [];
    for (const control of controls) assert.doesNotMatch(control, /workspace|tenant|client[-_ ]?id|account[-_ ]?id|owner[-_ ]?id/i, control);
    assert.doesNotMatch(html, /type="hidden"/);
    assert.doesNotMatch(text(html), /\b(select|choose|switch|change) (a |your )?(workspace|tenant|account|organi[sz]ation)\b/i);
    assert.doesNotMatch(html, /<select[^>]*>(?:(?!<\/select>).)*(workspace|tenant)/is);
  }
});

test("the page never says 'saved' for a failed or unconfirmed state", () => {
  const draft = productDraft();
  for (const save of [{ status: "idle" }, { status: "saving" }, { status: "error", code: "network" }, { status: "error", code: "malformed_response" }]) {
    const html = render({ initialSession: loadedSession(), initialState: { step: "review", draft, save } });
    assert.doesNotMatch(text(html), /Profile saved/, JSON.stringify(save));
  }
  const saved = render({ initialSession: loadedSession(), initialState: { step: "review", draft, save: { status: "saved" }, savedKey: JSON.stringify(payload(draft)) } });
  assert.match(text(saved), /Profile saved/);
  assert.match(text(saved), /The server accepted the save/);
});

test("wizard state used by the container carries no tenant or session data", () => {
  assert.deepEqual(Object.keys(initialWizardState()).sort(), ["announcement", "attempted", "demoReviewedKey", "draft", "focus", "keyCounter", "pending", "save", "savedKey", "step", "touched"]);
  assert.deepEqual(Object.keys(INITIAL_SESSION).sort(), ["phase", "version"]);
});
