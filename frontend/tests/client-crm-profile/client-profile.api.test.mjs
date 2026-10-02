/**
 * Client profile <-> /api/organization/client-profile (contract: api/routes/client_profile.py).
 *
 * `fetch` is MOCKED in every test: nothing here exercises a real server, and no
 * code in this repository issues the bearer tokens the service requires. What is
 * proven is how the client behaves for each status the service may send (read,
 * create, update, 401/403/404/409/413/415/422/503, malformed replies, network
 * failure), that the Bearer token comes only from an injected provider, that
 * identity is never sent or chosen client-side, that only the fields the service
 * stores are sent, and that "saved" is claimed only after a trustworthy 2xx.
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
const { toServerBody, storedKey, NOT_STORED_BY_SERVER } = await importFeature("lib/toServerBody.ts");
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
/** What the service returns: exactly `_present` in api/routes/client_profile.py. */
const serverReply = (draft = productDraft()) => {
  const body = toServerBody(payload(draft));
  return { ...body, social_accounts: body.social_accounts.map((a) => ({ ...a, connection_state: "not_connected" })) };
};
const TOKEN = "tok-abc.def-123";
const auth = { getAccessToken: async () => TOKEN };

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

// ----------------------------------------------------------------- request shape: bearer token, no identity

test("GET: one fixed URL, bearer token from the provider, no cookies, no body, no identity headers", async () => {
  const fetchImpl = mockFetch(() => reply(200, serverReply()));
  await api.fetchClientProfile({ fetchImpl, baseUrl: "", ...auth });
  assert.equal(fetchImpl.calls.length, 1);
  const call = fetchImpl.calls[0];
  assert.equal(call.url, "/api/organization/client-profile");
  assert.equal(call.method, "GET");
  assert.equal(call.credentials, "omit", "cookies are never sent");
  assert.equal(call.body, undefined);
  assert.deepEqual(Object.keys(call.headers).sort(), ["Accept", "Authorization"]);
  assert.equal(call.headers.Authorization, `Bearer ${TOKEN}`);
  assert.doesNotMatch(call.url, /[?#]|workspace|tenant|client_?id|tok-/i, "the token never reaches the URL");
});

test("POST and PATCH send only the fields the service stores, as JSON, with the bearer token", async () => {
  for (const [mode, method] of [["create", "POST"], ["update", "PATCH"]]) {
    const fetchImpl = mockFetch(() => reply(mode === "create" ? 201 : 200, serverReply()));
    await api.saveClientProfile(mode, payload(), { fetchImpl, baseUrl: "", ...auth });
    const call = fetchImpl.calls[0];
    assert.equal(call.method, method);
    assert.equal(call.credentials, "omit");
    assert.equal(call.url, "/api/organization/client-profile");
    assert.deepEqual(Object.keys(call.headers).sort(), ["Accept", "Authorization", "Content-Type"]);
    assert.equal(call.headers["Content-Type"], "application/json");
    const body = JSON.parse(call.body);
    assert.deepEqual(Object.keys(body).sort(), ["business_type", "company_name", "offerings", "segments", "social_accounts", "target_markets"], "the service rejects unknown keys");
    assert.deepEqual(body, toServerBody(payload()));
    assert.doesNotMatch(call.body, new RegExp(TOKEN), "the token is never in the body");
    const keys = [];
    (function walk(value) { if (Array.isArray(value)) value.forEach(walk); else if (value && typeof value === "object") for (const [k, v] of Object.entries(value)) { keys.push(k); walk(v); } })(body);
    assert.deepEqual(keys.filter((k) => /workspace|tenant|client_?id|owner|user_?id|token|password|schema|status|connect|categories|url|notes/i.test(k)), []);
  }
});

test("the shared API-origin helper decides the base URL", async () => {
  const fetchImpl = mockFetch(() => reply(404));
  await api.fetchClientProfile({ fetchImpl, baseUrl: "https://api.example.test", ...auth });
  assert.equal(fetchImpl.calls[0].url, "https://api.example.test/api/organization/client-profile");
  assert.equal(fetchImpl.calls[0].credentials, "omit");
});

test("without a usable token no request is made: no provider, a null token, a blank token and a throwing provider are all 'unauthenticated'", async () => {
  const providers = [undefined, async () => null, async () => "   ", async () => { throw new Error("sign-in unavailable"); }];
  for (const getAccessToken of providers) {
    const fetchImpl = mockFetch(() => reply(200, serverReply()));
    assert.deepEqual(await api.fetchClientProfile({ fetchImpl, getAccessToken }), { kind: "error", code: "unauthenticated" });
    await assert.rejects(api.saveClientProfile("create", payload(), { fetchImpl, getAccessToken }), (e) => e instanceof ProfileSaveError && e.code === "unauthenticated");
    assert.equal(fetchImpl.calls.length, 0, "nothing is sent while signed out");
  }
});

test("the token is asked for on every request and never kept by the client", async () => {
  let asked = 0;
  const getAccessToken = async () => `rotating-${++asked}`;
  const fetchImpl = mockFetch(() => reply(404));
  await api.fetchClientProfile({ fetchImpl, getAccessToken });
  await api.fetchClientProfile({ fetchImpl, getAccessToken });
  assert.deepEqual(fetchImpl.calls.map((c) => c.headers.Authorization), ["Bearer rotating-1", "Bearer rotating-2"]);
});

// ----------------------------------------------------------------- read (GET)

test("successful read: the service shape becomes a draft that holds only what the service stores", async () => {
  for (const draft of [productDraft(), serviceDraft()]) {
    const result = await api.fetchClientProfile({ fetchImpl: mockFetch(() => reply(200, serverReply(draft))), ...auth });
    assert.equal(result.kind, "ok");
    assert.equal(result.draft.companyName, "Example Demo Co");
    assert.deepEqual(result.draft.categories, [], "categories are not stored, so they are never invented");
    assert.deepEqual(result.draft.offerings.map((o) => [o.name, o.description, o.delivery, o.availability, o.sku, o.quantity]), [[draft.offerings[0].name, "", "", "", "", ""]]);
    assert.deepEqual(result.draft.socialAccounts.map((a) => [a.platform, a.handle, a.url, a.notes]), [["instagram", "example_demo", "", ""]]);
    assert.equal(storedKey(buildPayload(result.draft)), JSON.stringify(toServerBody(payload(draft))), "server -> draft -> stored fields is lossless");
  }
});

test("read: a leading @ on a stored handle is dropped for the form", async () => {
  const body = { ...serverReply(), social_accounts: [{ platform: "threads", handle: "@example_demo", connection_state: "not_connected" }] };
  const result = await api.fetchClientProfile({ fetchImpl: mockFetch(() => reply(200, body)), ...auth });
  assert.deepEqual(result.draft.socialAccounts.map((a) => [a.platform, a.handle]), [["threads", "example_demo"]]);
});

test("read: server extras such as a workspace identifier are ignored and never reach the draft", async () => {
  const body = { ...serverReply(), workspace_id: "ws-from-server", tenant: "t-1", owner_id: "o-1" };
  const result = await api.fetchClientProfile({ fetchImpl: mockFetch(() => reply(200, body)), ...auth });
  assert.equal(result.kind, "ok");
  assert.doesNotMatch(JSON.stringify(result), /ws-from-server|t-1|o-1|workspace|tenant/);
});

test("read: 404 is the normal 'no saved profile yet' state, not an error", async () => {
  assert.deepEqual(await api.fetchClientProfile({ fetchImpl: mockFetch(() => reply(404, { detail: { code: "profile_not_found" } })), ...auth }), { kind: "not_found" });
});

test("read: every status the service can send maps to its own code and leaks no server text", async () => {
  const expected = { 401: "unauthenticated", 403: "forbidden", 409: "conflict", 503: "unavailable", 400: "validation", 413: "validation", 415: "validation", 422: "validation", 500: "unknown", 502: "unknown", 429: "unknown" };
  for (const [status, code] of Object.entries(expected)) {
    const result = await api.fetchClientProfile({ fetchImpl: mockFetch(() => reply(Number(status), { detail: "SECRET-SERVER-TEXT" })), ...auth });
    assert.deepEqual(result, { kind: "error", code }, status);
    assert.doesNotMatch(JSON.stringify(result), /SECRET-SERVER-TEXT/, "server text is never surfaced");
  }
});

test("read: only the service's own profile_not_found 404 is a first visit; any other 404 is an error, never an empty create form", async () => {
  for (const response of [reply(404), reply(404, { detail: "Not Found" }), reply(404, { detail: { code: "something_else" } }), reply(404, undefined, { raw: "<html>proxy</html>" })]) {
    assert.deepEqual(await api.fetchClientProfile({ fetchImpl: mockFetch(() => response), ...auth }), { kind: "error", code: "not_found" });
  }
});

test("a 422 from the service's content screen has its own code on load and save; other 422s stay 'validation'", async () => {
  for (const code of ["content_rejected", "credentials_rejected"]) {
    assert.deepEqual(await api.fetchClientProfile({ fetchImpl: mockFetch(() => reply(422, { detail: { code, field: "offerings" } })), ...auth }), { kind: "error", code: "content_rejected" });
    await assert.rejects(api.saveClientProfile("create", payload(), { fetchImpl: mockFetch(() => reply(422, { detail: { code, field: "offerings" } })), ...auth }), (e) => e instanceof ProfileSaveError && e.code === "content_rejected");
  }
  for (const body of [{ detail: { code: "duplicate_entry", field: "segments" } }, { detail: "x" }, undefined]) {
    await assert.rejects(api.saveClientProfile("create", payload(), { fetchImpl: mockFetch(() => reply(422, body)), ...auth }), (e) => e.code === "validation");
  }
  assert.equal(api.codeForStatus(400, "content_rejected"), "validation", "the content code only counts on a 422");
  assert.match(SAVE_ERROR_TEXT.content_rejected, /content screen/);
});

test("read: lists up to the service's own limit of 25 load; the form then flags what it cannot save", async () => {
  const names = (n) => Array.from({ length: n }, (_, i) => `Entry ${i}`);
  const body = { ...serverReply(), segments: names(25), target_markets: names(25), offerings: names(25), social_accounts: Array.from({ length: 25 }, (_, i) => ({ platform: "x", handle: `h${i}`, connection_state: "not_connected" })) };
  const result = await api.fetchClientProfile({ fetchImpl: mockFetch(() => reply(200, body)), ...auth });
  assert.equal(result.kind, "ok");
  assert.equal(result.draft.segments.length, 25);
  const { validateProfile } = await importFeature("lib/validateProfile.ts");
  assert.ok(validateProfile(result.draft).errors.some((e) => e.code === "too_many" && e.path === "segments"), "10 is the form's own limit");
});

test("read: a network failure is its own code; an aborted request reports nothing", async () => {
  assert.deepEqual(await api.fetchClientProfile({ fetchImpl: mockFetch(() => { throw new TypeError("Failed to fetch"); }), ...auth }), { kind: "error", code: "network" });
  const controller = new AbortController();
  const fetchImpl = mockFetch(() => { controller.abort(); throw new DOMException("aborted", "AbortError"); });
  assert.deepEqual(await api.fetchClientProfile({ fetchImpl, signal: controller.signal, ...auth }), { kind: "aborted" });
});

test("read: replies that are not a valid profile are malformed_response, never a profile or an empty form", async () => {
  const good = serverReply();
  const bad = [
    reply(200, undefined, { raw: "<html>Please sign in</html>" }),       // login page after a redirect
    reply(200, undefined, { raw: "" }),                                    // empty
    reply(200, undefined, { raw: "{not json" }),
    reply(200, undefined, { raw: "x".repeat(api.MAX_RESPONSE_CHARS + 1) }),
    reply(200, [good]),
    reply(200, { ...good, business_type: "marketplace" }),
    reply(200, { ...good, company_name: 12 }),
    reply(200, { ...good, segments: "Coffee" }),
    reply(200, { ...good, segments: Array.from({ length: 26 }, (_, i) => `c${i}`) }),   // over the service's own limit of 25
    reply(200, { ...good, target_markets: [1] }),
    reply(200, { ...good, offerings: [{ name: "Kettle" }] }),              // the service returns names, not objects
    reply(200, { ...good, offerings: Array.from({ length: 26 }, (_, i) => `o${i}`) }),
    reply(200, { ...good, social_accounts: [{ platform: "instagram", handle: "x", connection_state: "connected" }] }),
    reply(200, { ...good, social_accounts: [{ platform: "instagram", handle: "x" }] }),
    reply(200, { ...good, social_accounts: [{ platform: "myspace", handle: "x", connection_state: "not_connected" }] }),
    reply(200, { ...good, social_accounts: [{ platform: "instagram", handle: 7, connection_state: "not_connected" }] }),
    reply(200, { ...good, social_accounts: "none" }),
    reply(200, { ...good, offerings: undefined }),
    reply(204),                                                            // a GET with nothing to show
    reply(202, good),
  ];
  for (const response of bad) {
    assert.deepEqual(await api.fetchClientProfile({ fetchImpl: mockFetch(() => response), ...auth }), { kind: "error", code: "malformed_response" }, `${response.status}`);
  }
});

test("read: a service that claims an account is connected is refused, so the UI can never show 'connected'", () => {
  const body = { ...serverReply(), social_accounts: [{ platform: "instagram", handle: "x", connection_state: "connected" }] };
  assert.equal(parseServerProfile(body), null);
});

test("the old draft-v0 shape is not a valid service reply", () => {
  assert.equal(parseServerProfile(payload()), null);
});

// ----------------------------------------------------------------- local payload -> service body

test("toServerBody: exactly the stored fields; categories, offering details, links and notes stay local", () => {
  const draft = productDraft({
    categories: ["Coffee equipment"],
    offerings: [offering({ name: "Kettle", description: "Gooseneck", sku: "K-1", quantity: "5" }), offering({ key: "o2", name: "Grinder", availability: "unknown", sku: "", quantity: "" })],
    socialAccounts: [
      { key: "s1", platform: "instagram", handle: "@Shop.demo", url: "https://instagram.com/shop.demo", notes: "main" },
      { key: "s2", platform: "other", handle: "", url: "https://example.com/page", notes: "" },
    ],
  });
  const body = toServerBody(buildPayload(draft));
  assert.deepEqual(body, {
    company_name: "Example Demo Co",
    business_type: "product",
    segments: ["Home baristas"],
    target_markets: ["Canada"],
    offerings: ["Kettle", "Grinder"],
    social_accounts: [{ platform: "instagram", handle: "Shop.demo" }],
  });
  assert.doesNotMatch(JSON.stringify(body), /Coffee equipment|Gooseneck|K-1|example\.com|main|link_status|connected/);
  assert.equal(NOT_STORED_BY_SERVER.length, 3);
});

test("storedKey ignores edits to tab-only fields but sees every stored field", () => {
  const base = productDraft();
  const key = storedKey(buildPayload(base));
  assert.equal(storedKey(buildPayload({ ...base, categories: ["Tea"] })), key);
  assert.equal(storedKey(buildPayload({ ...base, offerings: [offering({ sku: "Z-9", quantity: "99", description: "x" })] })), key);
  assert.notEqual(storedKey(buildPayload({ ...base, companyName: "Other Demo Co" })), key);
  assert.notEqual(storedKey(buildPayload({ ...base, offerings: [offering({ name: "Pot" })] })), key);
  assert.equal(storedKey(null), null);
});

// ----------------------------------------------------------------- save (POST / PATCH)

test("save: only 200 or 201 with a valid stored profile is a success", async () => {
  for (const response of [reply(200, serverReply()), reply(201, serverReply())]) {
    await api.saveClientProfile("create", payload(), { fetchImpl: mockFetch(() => response), ...auth });
  }
});

test("save: each failure status throws its own ProfileSaveError code and leaks no server text", async () => {
  const expected = { 401: "unauthenticated", 403: "forbidden", 404: "not_found", 409: "conflict", 503: "unavailable", 400: "validation", 413: "validation", 415: "validation", 422: "validation", 500: "unknown" };
  for (const mode of ["create", "update"]) {
    for (const [status, code] of Object.entries(expected)) {
      await assert.rejects(
        api.saveClientProfile(mode, payload(), { fetchImpl: mockFetch(() => reply(Number(status), { detail: "SQL error: Example Demo Co" })), ...auth }),
        (error) => error instanceof ProfileSaveError && error.code === code && !/SQL|Example/.test(error.message),
        `${mode} ${status}`,
      );
    }
  }
});

test("save: a network failure is 'network'; a 2xx the page cannot trust is 'malformed_response', never a success", async () => {
  await assert.rejects(api.saveClientProfile("update", payload(), { fetchImpl: mockFetch(() => { throw new TypeError("Failed to fetch"); }), ...auth }), (e) => e.code === "network");
  const untrusted = [
    reply(200, undefined, { raw: "<html>login</html>" }),
    reply(200, undefined, { raw: "" }),
    reply(200, { ok: true }),
    reply(201, { ...serverReply(), business_type: "other_than_allowed" }),
    reply(201, { ...serverReply(), social_accounts: [{ platform: "instagram", handle: "x", connection_state: "connected" }] }),
    reply(201, payload()),
    reply(202, serverReply()),
    reply(204),
    reply(205),
  ];
  for (const response of untrusted) {
    await assert.rejects(api.saveClientProfile("create", payload(), { fetchImpl: mockFetch(() => response), ...auth }), (e) => e instanceof ProfileSaveError && e.code === "malformed_response", `${response.status}`);
  }
});

test("save: an aborted request is never a success", async () => {
  const controller = new AbortController();
  const fetchImpl = mockFetch(() => { controller.abort(); throw new DOMException("aborted", "AbortError"); });
  await assert.rejects(api.saveClientProfile("update", payload(), { fetchImpl, signal: controller.signal, ...auth }), (e) => e instanceof ProfileSaveError && e.code === "network");
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
    await runLoad({ fetchImpl: mockFetch(() => response), ...auth }, (action) => seen.push(action));
    return seen.reduce(sessionReducer, INITIAL_SESSION);
  };
  const existing = await run(reply(200, serverReply()));
  assert.deepEqual([existing.phase, existing.mode, existing.version], ["ready", "update", 1]);
  assert.equal(existing.draft.companyName, "Example Demo Co");
  const none = await run(reply(404, { detail: { code: "profile_not_found" } }));
  assert.deepEqual([none.phase, none.mode, none.draft], ["ready", "create", EMPTY_DRAFT]);
  for (const [status, code] of [[401, "unauthenticated"], [403, "forbidden"], [409, "conflict"], [503, "unavailable"]]) {
    const failed = await run(reply(status));
    assert.deepEqual([failed.phase, failed.code], ["load_failed", code]);
  }
  const malformed = await run(reply(200, { nope: 1 }));
  assert.deepEqual([malformed.phase, malformed.code], ["load_failed", "malformed_response"]);
  const network = await (async () => { const seen = []; await runLoad({ fetchImpl: mockFetch(() => { throw new TypeError("x"); }), ...auth }, (a) => seen.push(a)); return seen.reduce(sessionReducer, INITIAL_SESSION); })();
  assert.equal(network.code, "network");
});

test("runLoad: an aborted load changes nothing after loadStarted (no late state from a stale request)", async () => {
  const controller = new AbortController();
  const seen = [];
  await runLoad({ fetchImpl: mockFetch(() => { controller.abort(); throw new DOMException("a", "AbortError"); }), signal: controller.signal, ...auth }, (a) => seen.push(a));
  assert.deepEqual(seen.map((a) => a.type), ["loadStarted"]);
});

test("makeSave: POST while no profile exists, PATCH after a successful create; failures never flip the mode", async () => {
  let session = sessionReducer(sessionReducer(INITIAL_SESSION, { type: "loadStarted" }), { type: "loadedNone" });
  const dispatch = (action) => { session = sessionReducer(session, action); };
  const outcomes = [reply(503), reply(201, serverReply()), reply(200, serverReply()), reply(409)];
  const fetchImpl = mockFetch((n) => outcomes[n - 1]);
  const save = makeSave(() => session, dispatch, { fetchImpl, ...auth });

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
  const save = makeSave(() => INITIAL_SESSION, () => {}, { fetchImpl: mockFetch(() => reply(200, serverReply())), ...auth });
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
  assert.match(text(render({ initialSession: { version: 0, phase: "load_failed", code: "unauthenticated" } })), /sign-in is required to load a saved profile, and no sign-in is connected/);
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

test("no token provider (the mounted routes): labelled fictional, not observed, not saved, not connected; sample tools only here", () => {
  const html = render({});
  assert.match(html, /data-mode="demo"/);
  assert.match(text(html), /Demo mode\. Nothing is saved or sent\./);
  assert.match(text(html), /signed-in connection to the profile service, which this page does not have yet/);
  assert.match(text(html), /sample data is fictional\. Nothing here is observed or saved, it is not connected to any account/);
  assert.match(text(html), /Fill with fictional sample data/);
  assert.doesNotMatch(text(html), /Loading your saved profile|could not be loaded/);
  const review = render({ initialState: { step: "review", draft: productDraft() } });
  assert.match(text(review), /Demo only: not saved/);
  assert.match(text(review), /Confirm review \(demo, not saved\)/);
  assert.doesNotMatch(text(review), /Profile saved|Confirm and save profile/);
});

test("the mode is chosen by the mounting code, not by the URL: the page reads no URL or storage state", () => {
  // Demo unless the host passes a token provider; nothing else can switch it on.
  assert.match(render({}), /data-mode="demo"/);
  assert.match(render({ initialSession: loadedSession() }), /data-mode="persistent"/);
  const spy = mockFetch(() => reply(200, serverReply()));
  assert.match(render({ fetchImpl: spy }), /data-mode="demo"/, "a fetch seam alone does not enable the live path");
  assert.equal(spy.calls.length, 0, "the demo makes no request");
  assert.match(text(render({ getAccessToken: async () => TOKEN })), /Loading your saved profile/);
});

test("a loaded profile says what the service keeps; the review lists what stays in this tab", () => {
  const html = render({ initialSession: loadedSession(), initialState: { step: "review" } });
  assert.match(html, /data-loaded-profile/);
  assert.match(text(html), /keeps only your company name, business type, segments, target markets, offering names and social handles/);
  assert.match(html, /data-not-stored/);
  assert.match(text(html), /Stays in this tab only/);
  for (const item of NOT_STORED_BY_SERVER) assert.ok(text(html).includes(item), item);
  const demo = render({ initialState: { step: "review", draft: productDraft() } });
  assert.doesNotMatch(demo, /data-not-stored|data-loaded-profile/);
});

test("no workspace, tenant or account selector exists in any state or step", () => {
  const states = [
    { initialSession: INITIAL_SESSION },
    { initialSession: { version: 0, phase: "load_failed", code: "forbidden" } },
    {},
    ...["company", "audience", "offerings", "social", "review"].map((step) => ({ initialSession: loadedSession(), initialState: { step } })),
    ...["company", "audience", "offerings", "social", "review"].map((step) => ({ initialState: { step, draft: productDraft() } })),
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
  const saved = render({ initialSession: loadedSession(), initialState: { step: "review", draft, save: { status: "saved" }, savedKey: storedKey(payload(draft)) } });
  assert.match(text(saved), /Profile saved/);
  assert.match(text(saved), /The server accepted the save of the fields it stores/);
});

test("wizard state used by the container carries no tenant or session data", () => {
  assert.deepEqual(Object.keys(initialWizardState()).sort(), ["announcement", "attempted", "demoReviewedKey", "draft", "focus", "keyCounter", "pending", "save", "savedKey", "step", "touched"]);
  assert.deepEqual(Object.keys(INITIAL_SESSION).sort(), ["phase", "version"]);
});
