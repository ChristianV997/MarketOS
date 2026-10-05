/**
 * Owner research portfolio: component tests.
 *
 * The REAL components are rendered with react-dom/server and the resulting DOM
 * is asserted (roles, tab stops, disabled state, aria wiring, escaping, copy).
 * Handlers on hook-free components are exercised by calling the component and
 * invoking the props on the elements it returns. Event-driven keyboard behaviour
 * and the live page (hooks, effects, network) are verified separately in real
 * Chromium; the pure key resolver is unit-tested in the adapters file.
 */
import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

import { importSrc } from "./helpers/load-ts.mjs";
import { CTX, FEATURE, NOW, packetWith, portfolioPayload, rankedRow } from "./helpers/owner-research-builders.mjs";

const { OwnerResearchWorkspace } = await importSrc(`${FEATURE}/components/OwnerResearchWorkspace`);
const { PortfolioProgressPanel } = await importSrc(`${FEATURE}/components/PortfolioProgressPanel`);
const { RankedOpportunityList, describeOption } = await importSrc(`${FEATURE}/components/RankedOpportunityList`);
const { adaptRankingPacket } = await importSrc(`${FEATURE}/lib/adaptRankingReadModel`);
const {
  adaptPortfolioPayload,
  evaluateDraftResearchGate,
  portfolioError,
  portfolioLoading,
  portfolioUnavailable,
} = await importSrc(`${FEATURE}/lib/adaptPortfolioReadModel`);
const { FIXTURE_PORTFOLIO_PAYLOAD, FIXTURE_RANKING_PACKET, FIXTURE_WORKSPACE_ID } = await importSrc(`${FEATURE}/fixtures/ownerResearchFixtures`);
const Page = (await importSrc(`${FEATURE}/OwnerResearchPortfolioPage`)).default;
const featureIndex = await importSrc(`${FEATURE}/index`);

// ----------------------------------------------------------------- helpers

const ranking = (packet, extra = {}) => adaptRankingPacket({ packet, loading: false, loadError: null, nowMs: NOW, ...extra });
const portfolio = (payload, ctx = CTX) => adaptPortfolioPayload(payload, ctx);
const render = (props) => renderToStaticMarkup(createElement(OwnerResearchWorkspace, props));

const LIVE = { fingerprint: { evidenceMode: "live_readonly" } };
const LIVE_ROWS = () => [
  rankedRow("cand-a", { rankIndex: 0, title: "Alpha lamp" }),
  rankedRow("cand-b", { rankIndex: 1, title: "Beta bottle" }),
  rankedRow("cand-c", { rankIndex: 2, title: "Gamma cable" }),
];
const liveRanking = (extra = {}) => ranking(packetWith(LIVE_ROWS(), LIVE), extra);
const livePair = () => ({ ranking: liveRanking(), portfolio: portfolio(portfolioPayload()) });

const matches = (html, re) => html.match(re) ?? [];
/** Attribute-order-independent tag access. */
const tagsOf = (html, name, filter = () => true) => matches(html, new RegExp(`<${name}\\b[^>]*>`, "g")).filter(filter);
const attr = (tag, name) => new RegExp(`\\s${name}="([^"]*)"`).exec(tag)?.[1] ?? null;
const hasAttr = (tag, name) => new RegExp(`\\s${name}(=""|=|\\s|/?>)`).test(tag);
const optionTags = (html) => tagsOf(html, "li", (tag) => attr(tag, "role") === "option");
const draftButtons = (html) => tagsOf(html, "button", (tag) => attr(tag, "data-draft-action") !== null);
const isDisabled = (tag) => hasAttr(tag, "disabled");
const detailsOpen = (html) => tagsOf(html, "details").map((tag) => hasAttr(tag, "open"));
const text = (html) =>
  html
    .replace(/<[^>]+>/g, " ")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ");
const ids = (html) => matches(html, /\sid="([^"]+)"/g).map((match) => /id="([^"]+)"/.exec(match)[1]);
const banners = (html, kind) => matches(html, new RegExp(`data-${kind}-banner="([a-z]+)"`, "g")).map((match) => /"([a-z]+)"/.exec(match)[1]);

/** Walk a React element tree returned by calling a hook-free component directly. */
function findElements(node, predicate, out = []) {
  if (node === null || node === undefined || typeof node !== "object") return out;
  if (Array.isArray(node)) {
    for (const child of node) findElements(child, predicate, out);
    return out;
  }
  if (predicate(node)) out.push(node);
  if (node.props) findElements(node.props.children, predicate, out);
  return out;
}

// ------------------------------------------------------- fixture / simulation

test("fixture: one merged fixture banner, 2/3 from distinct ids, and draft research stays disabled", () => {
  const html = render({
    ranking: ranking(FIXTURE_RANKING_PACKET),
    portfolio: portfolio(FIXTURE_PORTFOLIO_PAYLOAD, { expectedWorkspaceId: FIXTURE_WORKSPACE_ID, nowMs: NOW }),
    onDraftResearch: () => {},
  });
  assert.deepEqual(banners(html, "qualifier").filter((name) => name === "fixture"), ["fixture"], "one merged fixture banner, not one per scope");
  assert.match(html, /data-qualifier-scopes="ranking portfolio"/);
  assert.match(text(html), /Applies to: Ranking and Portfolio/);
  assert.match(text(html), /not live results/);
  assert.match(html, /data-portfolio-count="2"/);
  assert.match(html, />2\/3</);
  const buttons = draftButtons(html);
  assert.equal(buttons.length, 5);
  assert.ok(buttons.every(isDisabled), "no draft action is enabled for fixture data even with a connected handler");
  assert.match(html, /data-draft-gate="disabled"/);
  assert.match(text(html), /Fixture \/ simulation data cannot enable draft research/);
});

test("fixture: eligibility is never worded as a backend decision", () => {
  const eligible = render({
    ranking: liveRanking(),
    portfolio: portfolio(portfolioPayload({ evidence_mode: "fixture_only", draft_research: { eligible: true } })),
    onDraftResearch: () => {},
  });
  assert.match(text(eligible), /Fixture data reports eligible: a simulation, not a backend decision\./);
  assert.doesNotMatch(text(eligible), /Backend reports eligible/);
  assert.match(eligible, /data-eligibility="fixture"/);
  assert.ok(draftButtons(eligible).every(isDisabled) && draftButtons(eligible).length === 5);

  const notEligible = render({ ranking: liveRanking(), portfolio: portfolio(portfolioPayload({ evidence_mode: "simulated", draft_research: { eligible: false } })) });
  assert.match(text(notEligible), /Fixture data reports not eligible: a simulation, not a backend decision\./);
});

// ---------------------------------------------------- distinct surface states

test("states: loading, error, unavailable and empty ranking each render their own banner and no list", () => {
  const cases = [
    ["loading", adaptRankingPacket({ packet: null, loading: true, loadError: null, nowMs: NOW }), "Loading ranked opportunities", "status"],
    ["error", adaptRankingPacket({ packet: null, loading: false, loadError: "canonical_read_failed", nowMs: NOW }), "Ranking could not be loaded", "alert"],
    ["unavailable", adaptRankingPacket({ packet: null, loading: false, loadError: null, nowMs: NOW }), "Ranking read model unavailable", "status"],
    ["empty", ranking(packetWith([])), "No ranked candidates", "status"],
  ];
  const seenTitles = new Set();
  for (const [phase, model, title, role] of cases) {
    const html = render({ ranking: model, portfolio: portfolio(portfolioPayload()) });
    const bannerTags = tagsOf(html, "div", (tag) => attr(tag, "data-state-banner") === phase);
    assert.equal(bannerTags.length, 1, `${phase}: exactly one banner`);
    assert.equal(attr(bannerTags[0], "role"), role, `${phase}: role`);
    assert.ok(text(html).includes(title), `${phase}: copy`);
    assert.equal(optionTags(html).length, 0, `${phase}: no ranked rows are shown`);
    assert.ok(html.includes("data-ranked-empty"), `${phase}: a ranked-opportunities heading still exists`);
    for (const other of cases.map(([name]) => name).filter((name) => name !== phase)) {
      assert.equal(banners(html, "state").includes(other), false, `${phase} must not also show ${other}`);
    }
    seenTitles.add(title);
  }
  assert.equal(seenTitles.size, 4, "each state has its own copy");
});

test("states: unavailable and error explain themselves with the backend reason code; unavailable is not empty", () => {
  const unavailable = render({ ranking: liveRanking(), portfolio: portfolioUnavailable("endpoint_not_available", "ws-1") });
  assert.match(text(unavailable), /Portfolio read model unavailable/);
  assert.match(unavailable, /endpoint_not_available/);
  assert.doesNotMatch(text(unavailable), /No active curated candidates/);

  const failed = render({ ranking: liveRanking(), portfolio: portfolioError("http_500", "ws-1") });
  assert.match(text(failed), /Portfolio could not be loaded/);
  assert.equal(attr(tagsOf(failed, "div", (tag) => attr(tag, "data-state-banner") === "error")[0], "role"), "alert");
  assert.match(failed, /http_500/);

  const loading = render({ ranking: liveRanking(), portfolio: portfolioLoading("ws-1") });
  assert.match(text(loading), /Loading curated portfolio/, "the portfolio loading copy is pinned");
});

test("states: an unknown portfolio shows —/3 and never 0/3 (visually or to screen readers)", () => {
  for (const model of [portfolioLoading("ws-1"), portfolioUnavailable("endpoint_not_available", "ws-1"), portfolioError("http_500", "ws-1"), portfolioUnavailable("workspace_not_selected")]) {
    const html = render({ ranking: liveRanking(), portfolio: model });
    assert.match(html, /data-portfolio-count="unknown"/, model.phase);
    assert.match(html, />—\/3</, model.phase);
    assert.doesNotMatch(html, /(^|[^\d—])0\/3/, `${model.phase}: visual 0/3`);
    assert.doesNotMatch(text(html), /\b0 of 3\b/, `${model.phase}: sr-only 0 of 3`);
    assert.equal(tagsOf(html, "progress").length, 0, `${model.phase}: no progress bar without a count`);
    assert.match(text(html), /Progress unknown/);
  }
  assert.match(text(render({ ranking: liveRanking(), portfolio: portfolioLoading("ws-1") })), /Progress unknown: the portfolio is still loading/);
  assert.match(text(render({ ranking: liveRanking(), portfolio: portfolioUnavailable("x", "ws-1") })), /Progress unknown: the portfolio is not available/);
  assert.match(text(render({ ranking: liveRanking(), portfolio: portfolioLoading("ws-1") })), /Eligibility unknown: the portfolio is still loading/);
  assert.match(text(render({ ranking: liveRanking(), portfolio: portfolioError("x", "ws-1") })), /Eligibility unknown: the portfolio is not available/);
});

test("states: a loaded portfolio with no active candidates is a real 0/3, distinct from unknown", () => {
  const html = render({ ranking: liveRanking(), portfolio: portfolio(portfolioPayload({ items: [], draft_research: { eligible: false } })) });
  assert.match(html, /data-portfolio-count="0"/);
  assert.match(html, />0\/3</);
  assert.match(text(html), /0 of 3 distinct active candidates/);
  assert.match(text(html), /No active curated candidates/);
});

test("states: stale, partial, blocked and fixture banners are distinct, scoped, and co-occur in a stable order", () => {
  const each = {
    fixture: packetWith(LIVE_ROWS(), { fingerprint: { evidenceMode: "fixture_only" } }),
    stale: packetWith(LIVE_ROWS(), { state: "stale", ...LIVE }),
    partial: packetWith(LIVE_ROWS(), { state: "partial", ...LIVE }),
    blocked: packetWith(LIVE_ROWS(), { state: "blocked", blockedReasons: ["credential_missing"], ...LIVE }),
  };
  const titles = { fixture: "Fixture / simulation data", stale: "Stale evidence", partial: "Partial evidence", blocked: "Blocked by backend gates" };
  for (const [qualifier, packet] of Object.entries(each)) {
    const html = render({ ranking: ranking(packet), portfolio: portfolio(portfolioPayload()) });
    assert.deepEqual(banners(html, "qualifier"), [qualifier], `${qualifier}: exactly its own banner`);
    assert.match(html, new RegExp(`data-qualifier-banner="${qualifier}"[^>]*data-qualifier-scopes="ranking"|data-qualifier-scopes="ranking"[^>]*data-qualifier-banner="${qualifier}"`));
    assert.ok(text(html).includes(titles[qualifier]), qualifier);
  }
  const combined = render({
    ranking: ranking(packetWith(LIVE_ROWS(), { state: "stale", blockedReasons: ["credential_missing"], fingerprint: { evidenceMode: "fixture_only" } })),
    portfolio: portfolio(portfolioPayload()),
  });
  assert.deepEqual(banners(combined, "qualifier"), ["fixture", "stale"]);
  assert.match(combined, /credential_missing/);
});

test("states: reason details - blocked expands, advisory stays collapsed, errors expand, counts are honest", () => {
  const blocked = render({
    ranking: ranking(packetWith(LIVE_ROWS(), { state: "blocked", blockedReasons: ["credential_missing"], ...LIVE })),
    portfolio: portfolio(portfolioPayload()),
  });
  assert.deepEqual(detailsOpen(blocked), [true]);
  assert.match(blocked, /credential_missing/);

  const partial = render({
    ranking: ranking(packetWith(LIVE_ROWS(), { state: "partial", unavailableReasons: ["consumer_attention_api_unavailable"], ...LIVE })),
    portfolio: portfolio(portfolioPayload()),
  });
  assert.deepEqual(detailsOpen(partial), [false], "advisory reasons are collapsed until asked for");
  assert.match(partial, /consumer_attention_api_unavailable/, "but they remain in the DOM");

  assert.deepEqual(detailsOpen(render({ ranking: liveRanking(), portfolio: portfolioError("http_500", "ws-1") })), [true], "error reasons are open");

  const many = Array.from({ length: 25 }, (_, index) => `warning_${index}`);
  const overflow = render({ ranking: ranking(packetWith(LIVE_ROWS(), { warnings: many, ...LIVE })), portfolio: portfolio(portfolioPayload()) });
  assert.match(text(overflow), /Ranking details \(25\)/, "the summary count is the true total");
  assert.match(overflow, /data-reasons-hidden="5"/);
  assert.match(text(overflow), /\+5 more not shown/);
  assert.ok(overflow.includes("warning_19") && !overflow.includes("warning_20"), "exactly the first 20 are listed");
});

test("states: the details summary is a full-height touch target", () => {
  const html = render({ ranking: liveRanking(), portfolio: portfolioUnavailable("endpoint_not_available", "ws-1") });
  assert.match(tagsOf(html, "summary")[0], /py-3\.5/, "summary padding gives a 44px target");
});

// ------------------------------------------------ warnings and dropped rows

test("integrity: duplicate and malformed ranked rows are surfaced, never silently dropped", () => {
  const rows = [
    rankedRow("cand-a", { rankIndex: 0, title: "First" }),
    rankedRow("cand-a", { rankIndex: 1, title: "Duplicate of first" }),
    rankedRow("", { rankIndex: 2 }),
    rankedRow("cand-b", { rankIndex: 3, title: "Second" }),
  ];
  const html = render({ ranking: ranking(packetWith(rows, LIVE)), portfolio: portfolio(portfolioPayload()) });
  assert.deepEqual(optionTags(html).map((tag) => attr(tag, "data-candidate-id")), ["cand-a", "cand-b"]);
  assert.match(html, /data-hidden-rows="2"/);
  assert.match(
    text(html),
    /2 ranked rows not shown: 1 duplicate candidate ID, 1 malformed candidate ID\./,
    "the notice itself names what was left out, so it does not depend on the collapsed details",
  );
  assert.match(html, /duplicate_candidate_id:cand-a/, "the warning is listed in the ranking details");
  assert.match(html, /invalid_candidate_id/);
  assert.deepEqual(banners(html, "qualifier"), ["partial"]);

  const single = render({ ranking: ranking(packetWith([rankedRow("cand-a"), rankedRow("cand-a", { rankIndex: 1 })], LIVE)), portfolio: portfolio(portfolioPayload()) });
  assert.match(text(single), /1 ranked row not shown: 1 duplicate candidate ID\./);
});

test("integrity: rows cut off by the display cap are counted, not reported as one", () => {
  const rows = Array.from({ length: 205 }, (_, index) => rankedRow(`cand-${index}`, { rankIndex: index }));
  const html = render({ ranking: ranking(packetWith(rows, LIVE)), portfolio: portfolio(portfolioPayload()) });
  assert.equal(optionTags(html).length, 200);
  assert.match(html, /data-hidden-rows="5"/);
  assert.match(text(html), /5 ranked rows not shown: 5 past the 200-row limit\./);
  assert.match(html, /rows_truncated:5/, "the count is also in the ranking details");
});

test("integrity: no dropped rows means no notice (an absent list is not a zero)", () => {
  const clean = render({ ranking: liveRanking(), portfolio: portfolio(portfolioPayload()) });
  assert.doesNotMatch(clean, /data-hidden-rows/);
  const { rows } = liveRanking();
  for (const hiddenRows of [undefined, []]) {
    const list = renderToStaticMarkup(createElement(RankedOpportunityList, { rows, selectedId: null, onSelect() {}, hiddenRows }));
    assert.doesNotMatch(list, /data-hidden-rows/);
  }
});

test("integrity: rank inconsistencies are listed as warnings and raise the partial banner", () => {
  const html = render({ ranking: ranking(packetWith([rankedRow("a", { rankIndex: 2 }), rankedRow("b", { rankIndex: 1 })], LIVE)), portfolio: portfolio(portfolioPayload()) });
  assert.match(html, /rank_order_inconsistent:b/);
  assert.deepEqual(banners(html, "qualifier"), ["partial"]);
});

// --------------------------------------------------------- run summary honesty

test("run summary: network calls are never reported as a definite 'no'", () => {
  const none = render({ ranking: ranking(packetWith(LIVE_ROWS(), { fingerprint: { evidenceMode: "live_readonly", networkCalls: false } })), portfolio: portfolio(portfolioPayload()) });
  assert.match(none, /data-run-network="none_reported"/);
  assert.match(text(none), /Network calls: none reported/);
  assert.doesNotMatch(text(none), /Network calls reported: no/);

  const some = render({ ranking: ranking(packetWith(LIVE_ROWS(), { fingerprint: { evidenceMode: "live_readonly", networkCalls: true } })), portfolio: portfolio(portfolioPayload()) });
  assert.match(some, /data-run-network="reported"/);
  assert.match(text(some), /Network calls: reported by the backend/);
});

test("run summary: the evidence-mode explanation is visible up front, not only in the detail panel", () => {
  for (const [mode, phrase] of [
    ["manual", "Operator-supplied screening evidence. Not live validated."],
    ["unknown", "Provenance is not reported."],
    ["simulated", "Derived planning values."],
    ["live_readonly", "read-only live path"],
  ]) {
    const html = render({ ranking: ranking(packetWith(LIVE_ROWS(), { fingerprint: { evidenceMode: mode } })), portfolio: portfolio(portfolioPayload()) });
    const header = html.slice(html.indexOf('aria-label="Ranking run provenance"'), html.indexOf("Curated portfolio"));
    assert.ok(text(header).includes(phrase), `${mode}: ${phrase}`);
    assert.match(header, new RegExp(`data-run-mode="${mode}"`));
  }
});

// --------------------------------------------------------- portfolio progress

test("progress: SKU/offer/quantity rows and duplicate ids never inflate X/3", () => {
  const html = render({
    ranking: liveRanking(),
    portfolio: portfolio(
      portfolioPayload({
        items: [
          { candidate_id: "cand-a", status: "active", sku: "S1", quantity: 900, supplier_offer_count: 12 },
          { candidate_id: "cand-a", status: "active", sku: "S2", quantity: 100 },
          { candidate_id: "cand-b", status: "active", sku: "S3" },
          { candidate_id: "cand-c", status: "removed" },
        ],
        draft_research: { eligible: false },
      }),
    ),
  });
  assert.match(html, /data-portfolio-count="2"/);
  assert.match(html, />2\/3</);
  const bar = tagsOf(html, "progress")[0];
  assert.deepEqual([attr(bar, "value"), attr(bar, "max"), attr(bar, "aria-hidden")], ["2", "3", "true"], "visual bar only; the count is announced once");
  assert.match(text(html), /SKUs, supplier offers, quantities and repeated rows are never counted/);
  assert.match(text(html), /1 repeated row\(s\) for already-counted IDs were ignored/);
  assert.match(text(html), /1 inactive, removed or archived entry is not counted/);
});

test("progress: more than three distinct ids reads honestly (5/3) with the bar clamped", () => {
  const items = ["a", "b", "c", "d", "e"].map((id) => ({ candidate_id: id, status: "active" }));
  const html = render({ ranking: liveRanking(), portfolio: portfolio(portfolioPayload({ items })) });
  assert.match(html, />5\/3</);
  assert.equal(attr(tagsOf(html, "progress")[0], "value"), "3");
});

test("progress: malformed entries are reported, never silently counted, and block drafting", () => {
  const html = render({
    ranking: liveRanking(),
    portfolio: portfolio(portfolioPayload({ items: [{ candidate_id: "cand-a", status: "active" }, { candidate_id: " ", status: "active" }, { candidate_id: "cand-b", status: "???" }] })),
    onDraftResearch: () => {},
  });
  assert.match(html, />1\/3</);
  assert.match(text(html), /1 entry with a missing or malformed candidate ID was ignored/);
  assert.match(text(html), /1 entry with an unknown status was ignored/);
  assert.deepEqual(banners(html, "qualifier"), ["partial"]);
  assert.ok(draftButtons(html).every(isDisabled));
});

test("progress: portfolio ids outside the current ranking are flagged; ranked ids in the portfolio are marked", () => {
  const html = render({
    ranking: liveRanking(),
    portfolio: portfolio(portfolioPayload({ items: [{ candidate_id: "cand-a", status: "active" }, { candidate_id: "legacy-only", status: "active" }] })),
  });
  assert.match(text(html), /legacy-only \(not in current ranking\)/);
  const alpha = optionTags(html).find((tag) => attr(tag, "data-candidate-id") === "cand-a");
  const beta = optionTags(html).find((tag) => attr(tag, "data-candidate-id") === "cand-b");
  assert.match(attr(alpha, "aria-label"), /in curated portfolio/);
  assert.doesNotMatch(attr(beta, "aria-label"), /in curated portfolio/);
});

// ----------------------------------------------------------- draft research

test("draft research: all five actions are native-disabled unless the backend explicitly reports eligibility", () => {
  const scenarios = {
    "three ids but eligibility not reported": portfolioPayload({ draft_research: undefined }),
    "backend says not eligible": portfolioPayload({ draft_research: { eligible: false, reasons: ["supplier_gate_open"] } }),
    "eligibility is a string": portfolioPayload({ draft_research: { eligible: "true" } }),
    "eligible but only two ids": portfolioPayload({ items: [{ candidate_id: "cand-a", status: "active" }, { candidate_id: "cand-b", status: "active" }] }),
    "eligible with an unverifiable date": portfolioPayload({ generated_at: "not-a-date" }),
  };
  for (const [name, payload] of Object.entries(scenarios)) {
    const html = render({ ranking: liveRanking(), portfolio: portfolio(payload), onDraftResearch: () => {} });
    const buttons = draftButtons(html);
    assert.equal(buttons.length, 5, `${name}: five actions exist`);
    assert.ok(buttons.every(isDisabled), `${name}: every action disabled`);
    assert.match(html, /data-draft-gate="disabled"/, name);
    assert.ok(ids(html).includes("owner-draft-reasons"), `${name}: reasons are visible`);
  }
  const notEligible = render({
    ranking: liveRanking(),
    portfolio: portfolio(portfolioPayload({ draft_research: { eligible: false, reasons: ["supplier_gate_open"] } })),
    onDraftResearch: () => {},
  });
  assert.match(text(notEligible), /Backend reports not eligible for draft research/);
  assert.match(notEligible, /supplier_gate_open/);
  assert.match(notEligible, />3\/3</, "3/3 progress does not by itself unlock anything");
});

test("draft research: a connected handler plus explicit backend eligibility on non-fixture data enables all five actions", () => {
  const { ranking: liveRank, portfolio: livePort } = livePair();
  const html = render({ ranking: liveRank, portfolio: livePort, onDraftResearch: () => {} });
  const buttons = draftButtons(html);
  assert.equal(buttons.length, 5);
  assert.ok(buttons.every((tag) => !isDisabled(tag)), "actions are enabled");
  assert.match(html, /data-draft-gate="enabled"/);
  assert.ok(!ids(html).includes("owner-draft-reasons"));
  assert.match(text(html), /Backend reports eligible for draft research/);
  assert.deepEqual(buttons.map((tag) => attr(tag, "data-draft-action")), ["target_markets", "personas", "brand_ad_strategy", "social_channels", "storefront_landing"]);
});

test("draft research: eligibility without a connected service stays disabled and says so", () => {
  const { ranking: liveRank, portfolio: livePort } = livePair();
  const html = render({ ranking: liveRank, portfolio: livePort });
  assert.equal(draftButtons(html).length, 5);
  assert.ok(draftButtons(html).every(isDisabled));
  assert.match(text(html), /No draft-research service is connected to this page yet/);
});

test("draft research: every button is a real type=button and the group is labelled and described", () => {
  const html = render({ ranking: liveRanking(), portfolio: portfolio(portfolioPayload({ draft_research: undefined })) });
  const buttons = draftButtons(html);
  assert.equal(buttons.length, 5);
  assert.ok(buttons.every((tag) => attr(tag, "type") === "button"));
  const group = tagsOf(html, "div", (tag) => attr(tag, "role") === "group")[0];
  assert.equal(attr(group, "aria-labelledby"), "owner-draft-heading");
  assert.equal(attr(group, "aria-describedby"), "owner-draft-reasons");
});

test("draft research: clicking an enabled action emits exactly {actionId, activeCandidateIds} - a copy, never the model's array", () => {
  const model = portfolio(portfolioPayload({ items: [{ candidate_id: "cand-a", status: "active", quantity: 900, sku: "S1" }, { candidate_id: "cand-b", status: "active" }, { candidate_id: "cand-c", status: "active" }] }));
  const gate = evaluateDraftResearchGate(model, { handlerConnected: true });
  assert.equal(gate.enabled, true);
  const calls = [];
  const tree = PortfolioProgressPanel({ portfolio: model, gate, rankedCandidateIds: null, onDraftResearch: (request) => calls.push(request) });
  const buttons = findElements(tree, (node) => node.type === "button");
  assert.equal(buttons.length, 5);
  assert.ok(buttons.every((button) => button.props.disabled === false));
  for (const button of buttons) button.props.onClick();
  assert.deepEqual(calls.map((call) => call.actionId), ["target_markets", "personas", "brand_ad_strategy", "social_channels", "storefront_landing"]);
  for (const call of calls) {
    assert.deepEqual(Object.keys(call).sort(), ["actionId", "activeCandidateIds"], "no counts, SKUs, quantities or offers");
    assert.deepEqual(call.activeCandidateIds, ["cand-a", "cand-b", "cand-c"]);
    assert.notEqual(call.activeCandidateIds, model.activeCandidateIds, "a copy, so the integrator cannot mutate the model");
  }
  calls[0].activeCandidateIds.push("tampered");
  assert.deepEqual(model.activeCandidateIds, ["cand-a", "cand-b", "cand-c"]);
});

test("draft research: a disabled gate never emits, even if a click handler is invoked directly", () => {
  const model = portfolio(portfolioPayload({ draft_research: { eligible: false } }));
  const gate = evaluateDraftResearchGate(model, { handlerConnected: true });
  assert.equal(gate.enabled, false);
  const calls = [];
  const tree = PortfolioProgressPanel({ portfolio: model, gate, rankedCandidateIds: null, onDraftResearch: (request) => calls.push(request) });
  const buttons = findElements(tree, (node) => node.type === "button");
  assert.equal(buttons.length, 5);
  for (const button of buttons) {
    assert.equal(button.props.disabled, true);
    button.props.onClick();
  }
  assert.deepEqual(calls, [], "the click path re-checks the gate");
  // No handler at all: an enabled gate still cannot throw or emit.
  const enabledGate = { enabled: true, reasons: [] };
  const silent = PortfolioProgressPanel({ portfolio: model, gate: enabledGate, rankedCandidateIds: null });
  assert.doesNotThrow(() => findElements(silent, (node) => node.type === "button").forEach((button) => button.props.onClick()));
});

// ------------------------------------------------- ranked list: semantics + a11y

test("list: backend order, one option per candidate, a single tab stop on the selected option", () => {
  const html = render({ ...livePair() });
  const options = optionTags(html);
  assert.deepEqual(options.map((tag) => attr(tag, "data-candidate-id")), ["cand-a", "cand-b", "cand-c"]);
  assert.deepEqual(options.map((tag) => attr(tag, "aria-selected")), ["true", "false", "false"]);
  assert.deepEqual(options.map((tag) => attr(tag, "tabindex")), ["0", "-1", "-1"]);
  assert.ok(options.every((tag) => attr(tag, "aria-label")), "each option has an accessible name");
  const listbox = tagsOf(html, "ul", (tag) => attr(tag, "role") === "listbox")[0];
  assert.equal(attr(listbox, "aria-labelledby"), "owner-ranked-heading");
  assert.equal(attr(listbox, "aria-describedby"), "owner-ranked-hint");
  assert.equal(attr(listbox, "aria-orientation"), "vertical");
});

test("list: the rendered DOM keeps backend order even when a portfolio holds only the last-ranked id", () => {
  const rows = [
    rankedRow("first-but-weakest", { rankIndex: 0, confidence: 0.1, evidenceCompleteness: 0.1 }),
    rankedRow("second-but-strongest", { rankIndex: 1, confidence: 0.9, evidenceCompleteness: 0.9 }),
    rankedRow("third-mid", { rankIndex: 2, confidence: 0.5, evidenceCompleteness: 0.5 }),
  ];
  const html = render({
    ranking: ranking(packetWith(rows, LIVE)),
    portfolio: portfolio(portfolioPayload({ items: [{ candidate_id: "third-mid", status: "active" }] })),
  });
  assert.deepEqual(optionTags(html).map((tag) => attr(tag, "data-candidate-id")), ["first-but-weakest", "second-but-strongest", "third-mid"]);
});

test("list: initialSelectedId moves the tab stop and the detail panel; unknown ids fall back to the first row", () => {
  const props = livePair();
  const second = render({ ...props, initialSelectedId: "cand-b" });
  assert.deepEqual(optionTags(second).map((tag) => attr(tag, "tabindex")), ["-1", "0", "-1"]);
  assert.match(second, /Candidate ID: cand-b/);

  const fallback = render({ ...props, initialSelectedId: "does-not-exist" });
  assert.deepEqual(optionTags(fallback).map((tag) => attr(tag, "tabindex")), ["0", "-1", "-1"]);
  assert.match(fallback, /Candidate ID: cand-a/);
});

test("list: the label carries rank, title, evidence, gates, portfolio and freshness; the id is the description", () => {
  const rows = ranking(packetWith([rankedRow("cand-a", { rankIndex: 0, title: "Alpha lamp", hardGates: ["g1"] }), rankedRow("cand-b", { rankIndex: 1, title: "Beta", hardGates: ["g1", "g2"] })], LIVE)).rows;
  const label = describeOption({ ...rows[0], inPortfolio: true });
  assert.match(label, /^Rank 1, Alpha lamp, evidence /);
  assert.match(label, /1 blocking gate,/, "singular");
  assert.match(label, /in curated portfolio/);
  assert.match(label, /freshness not reported$/);
  assert.doesNotMatch(label, /cand-a/, "the id is not re-read as part of every name");
  assert.match(describeOption(rows[1]), /2 blocking gates/, "plural");
  assert.doesNotMatch(describeOption(rows[1]), /in curated portfolio/);

  const html = render({ ...livePair() });
  const first = optionTags(html)[0];
  const describedBy = attr(first, "aria-describedby");
  assert.equal(describedBy, "owner-opp-id-0");
  assert.match(html, new RegExp(`id="${describedBy}"[^>]*>cand-a<`), "the description element holds the candidate id");
});

test("list: a second jump link follows the list so touch users never scroll back up", () => {
  const html = render({ ...livePair() });
  const links = tagsOf(html, "a", (tag) => attr(tag, "href") === "#owner-opportunity-detail");
  assert.equal(links.length, 2);
  assert.ok(links.every((tag) => /lg:hidden/.test(tag)));
  const listboxStart = html.indexOf(tagsOf(html, "ul", (tag) => attr(tag, "role") === "listbox")[0]);
  const listboxEnd = html.indexOf("</ul>", listboxStart);
  assert.ok(html.indexOf(links[0]) < listboxStart, "one link before the list");
  assert.ok(html.lastIndexOf(links[1]) > listboxEnd, "one link after the list");
});

test("a11y: every aria-labelledby/describedby target exists, ids are unique, headings are ordered", () => {
  const html = render({ ...livePair() });
  const all = ids(html);
  assert.equal(new Set(all).size, all.length, "duplicate DOM ids");
  for (const reference of matches(html, /aria-(?:labelledby|describedby)="([^"]+)"/g)) {
    const target = /="([^"]+)"/.exec(reference)[1];
    assert.ok(all.includes(target), `dangling reference to #${target}`);
  }
  assert.equal(matches(html, /<h1\b/g).length, 1, "exactly one h1");
  const levels = matches(html, /<h([1-4])\b/g).map((tag) => Number(tag[2]));
  for (let index = 1; index < levels.length; index += 1) {
    assert.ok(levels[index] - levels[index - 1] <= 1, `heading level jumps ${levels[index - 1]} -> ${levels[index]}`);
  }
});

test("a11y: a persistent polite live region announces the surface summary", () => {
  const ready = render({ ...livePair() });
  const region = tagsOf(ready, "p", (tag) => hasAttr(tag, "data-live-summary"))[0];
  assert.deepEqual([attr(region, "role"), attr(region, "aria-live"), attr(region, "aria-atomic")], ["status", "polite", "true"]);
  assert.match(region, /sr-only/);
  assert.match(text(ready), /Ranking ready: 3 candidates in backend order\. Portfolio: 3 of 3 distinct active candidates\./);

  const unknown = render({ ranking: adaptRankingPacket({ packet: null, loading: true, loadError: null, nowMs: NOW }), portfolio: portfolioLoading("ws-1") });
  assert.match(text(unknown), /Ranking is loading\. Portfolio is loading\./);
  assert.doesNotMatch(text(unknown), /\b0 of 3\b/);
  assert.equal(tagsOf(unknown, "p", (tag) => hasAttr(tag, "data-live-summary")).length, 1, "the region exists in every state, so changes are announced");
});

test("a11y: every ranked-opportunities state has exactly one heading with a unique id", () => {
  for (const model of [
    adaptRankingPacket({ packet: null, loading: true, loadError: null, nowMs: NOW }),
    adaptRankingPacket({ packet: null, loading: false, loadError: "canonical_read_failed", nowMs: NOW }),
    ranking(packetWith([])),
    liveRanking(),
  ]) {
    const html = render({ ranking: model, portfolio: portfolio(portfolioPayload()) });
    assert.equal(ids(html).filter((id) => id === "owner-ranked-heading").length, 1, model.phase);
  }
});

test("a11y: state is never colour-only - chips and banners carry text", () => {
  const html = render({ ranking: ranking(FIXTURE_RANKING_PACKET), portfolio: portfolio(FIXTURE_PORTFOLIO_PAYLOAD, { expectedWorkspaceId: FIXTURE_WORKSPACE_ID, nowMs: NOW }) });
  assert.ok(text(html).includes("Evidence: fixture"));
  assert.ok(text(html).includes("Partial evidence"));
  assert.ok(text(html).includes("Freshness not reported"));
  assert.match(html, /aria-label="Ranking run provenance"/);
});

// ------------------------------------------------------------- detail panel

test("detail: null scores read Not reported, never 0%", () => {
  const cells = rankedRow("solo").pillarCells.map((cell) => ({ ...cell, score: null, detail: null }));
  const model = ranking(packetWith([rankedRow("solo", { title: "Solo", evidenceCompleteness: null, confidence: null, pillarCells: cells, missingEvidence: [], hardGates: [], conflicts: [], assumptions: [], evidenceReferences: [], replayIdentity: null })], LIVE));
  const html = render({ ranking: model, portfolio: portfolio(portfolioPayload()) });
  const detail = html.slice(html.indexOf('id="owner-opportunity-detail"'));
  assert.doesNotMatch(detail, /\b0%/, "no zero percentages for missing values");
  assert.match(text(detail), /Evidence completeness Not reported/);
  assert.match(text(detail), /Confidence Not reported/);
  assert.match(text(detail), /No evidence gaps were reported by the backend/);
  assert.match(text(detail), /No evidence references were reported/);
  assert.match(text(detail), /Replay identity Not reported/);
  assert.equal(matches(text(detail), /Reported score: Not reported/g).length, cells.length, "every pillar reads Not reported");
});

test("detail: an explicit reported zero is shown as 0%, distinct from not reported", () => {
  const cells = rankedRow("zero").pillarCells.map((cell, index) => ({ ...cell, score: index === 0 ? 0 : null }));
  const model = ranking(packetWith([rankedRow("zero", { pillarCells: cells, evidenceCompleteness: 0 })], LIVE));
  const html = render({ ranking: model, portfolio: portfolio(portfolioPayload()) });
  const detail = html.slice(html.indexOf('id="owner-opportunity-detail"'));
  assert.match(text(detail), /Evidence completeness 0%/);
  assert.match(text(detail), /Reported score: 0%/);
});

test("detail: pillars are a reflowing labelled list (no scroll region); gaps, gates, conflicts, provenance and freshness are shown", () => {
  const model = ranking(
    packetWith([
      rankedRow("cand-a", {
        title: "Alpha lamp",
        missingEvidence: ["supplier_lead_time"],
        hardGates: ["credential_missing"],
        conflicts: ["price_mismatch"],
        assumptions: ["margin_assumed"],
        evidenceReferences: ["ref-1"],
        replayIdentity: "replay-xyz",
        freshnessExpiry: "2026-09-01T00:00:00Z",
      }),
    ], LIVE),
  );
  const html = render({ ranking: model, portfolio: portfolio(portfolioPayload()) });
  const detail = html.slice(html.indexOf('id="owner-opportunity-detail"'));
  assert.ok(tagsOf(detail, "ul", (tag) => attr(tag, "aria-label") === "Evidence pillars for Alpha lamp, exactly as reported").length === 1);
  assert.equal(tagsOf(detail, "li", (tag) => /^[a-z_]+$/.test(attr(tag, "data-pillar") ?? "")).length, 6, "one item per reported pillar");
  assert.match(text(detail), /Market Status: partial Reported score: 58%/);
  assert.match(text(detail), /Attention Status: unavailable Reported score: Not reported/);
  assert.doesNotMatch(detail, /<table\b/, "no table: it forced a horizontal scroll region that keyboards cannot reach");
  assert.doesNotMatch(detail, /overflow-x-auto|overflow-auto|overflow-scroll/);
  for (const expected of ["supplier_lead_time", "credential_missing", "price_mismatch", "margin_assumed", "ref-1", "replay-xyz"]) {
    assert.ok(detail.includes(expected), `${expected} is shown`);
  }
  assert.match(detail, /data-freshness-status="stale"/);
  assert.match(text(detail), /Expired 2026-09-01T00:00:00Z/);
  assert.match(text(detail), /Advisory only/);
});

test("detail: a fixture packet's evidence mode is spelled out as not live validated", () => {
  const html = render({ ranking: ranking(FIXTURE_RANKING_PACKET), portfolio: portfolio(FIXTURE_PORTFOLIO_PAYLOAD, { expectedWorkspaceId: FIXTURE_WORKSPACE_ID, nowMs: NOW }) });
  assert.match(text(html), /Fixture only\. Offline screening fixture\. Not live validated/);
});

// ---------------------------------------------------------------- security

test("security: untrusted strings are escaped, never injected as markup", () => {
  const hostile = "<script>alert(1)</script>";
  const model = ranking(
    packetWith([
      rankedRow('id"><img src=x onerror=alert(1)>', { title: hostile }),
      rankedRow("cand-safe", { rankIndex: 1, title: `${hostile} & <b>bold</b>`, missingEvidence: [hostile], evidenceReferences: ["javascript:alert(1)"] }),
    ], LIVE),
  );
  const html = render({ ranking: model, portfolio: portfolio(portfolioPayload()) });
  assert.doesNotMatch(html, /<script/i);
  assert.doesNotMatch(html, /<img/i);
  assert.doesNotMatch(html, /<b>bold/i);
  assert.match(html, /&lt;script&gt;/);
  assert.equal(tagsOf(html, "a", (tag) => /^\s*javascript:/i.test(attr(tag, "href") ?? "")).length, 0, "evidence references are text, never links");
});

// -------------------------------------------------------------------- page

test("page: explicit fixture source renders labelled fixture data without a window or network", () => {
  const html = renderToStaticMarkup(createElement(Page, { source: "fixture" }));
  assert.match(html, /data-owner-research-workspace/);
  assert.ok(banners(html, "qualifier").includes("fixture"));
  const buttons = draftButtons(html);
  assert.equal(buttons.length, 5);
  assert.ok(buttons.every(isDisabled));
});

test("page: ?source=fixture in the URL selects the fixture; without it the page is live and never falls back to fixtures", () => {
  try {
    globalThis.window = { location: { search: "?source=fixture" } };
    const fromUrl = renderToStaticMarkup(createElement(Page));
    assert.ok(banners(fromUrl, "qualifier").includes("fixture"), "the URL parameter selects the fixture source");
  } finally {
    delete globalThis.window;
  }

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const live = renderToStaticMarkup(createElement(QueryClientProvider, { client }, createElement(Page, { workspaceId: "ws-1" })));
  assert.match(text(live), /Loading ranked opportunities/, "the live page starts from the canonical read (loading), not from data");
  assert.match(text(live), /Loading curated portfolio/);
  assert.equal(banners(live, "qualifier").length, 0, "no fixture banner, so no fixture data leaked into the live path");
  assert.doesNotMatch(live, /cand-espresso-01/, "fixture ids never appear in the live path");
  assert.match(live, /data-portfolio-count="unknown"/);
  assert.ok(draftButtons(live).every(isDisabled) && draftButtons(live).length === 5);
});

test("page: the workspace comes from the prop or the URL and there is no default tenant", () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const renderLive = (props) => renderToStaticMarkup(createElement(QueryClientProvider, { client }, createElement(Page, props)));

  const none = renderLive({});
  assert.match(text(none), /Portfolio read model unavailable/);
  assert.match(none, /workspace_not_selected/);
  assert.match(text(none), /No workspace selected/);

  try {
    globalThis.window = { location: { search: "?workspace_id=ws-from-url" } };
    const fromUrl = renderLive({});
    assert.match(text(fromUrl), /Workspace ws-from-url/);
    const propWins = renderLive({ workspaceId: "ws-prop" });
    assert.match(text(propWins), /Workspace ws-prop/, "an explicit prop wins over the URL");
    const blank = renderLive({ workspaceId: "   " });
    assert.match(blank, /workspace_not_selected/, "a blank workspace is not a workspace");
  } finally {
    delete globalThis.window;
  }
});

test("page: the public index exports the page, workspace, adapters and contract constants", () => {
  assert.equal(typeof featureIndex.OwnerResearchPortfolioPage, "function");
  assert.equal(typeof featureIndex.OwnerResearchWorkspace, "function");
  for (const name of ["adaptRankingPacket", "adaptPortfolioPayload", "evaluateDraftResearchGate", "portfolioError", "portfolioLoading", "portfolioUnavailable", "fetchOwnerPortfolioPayload", "buildPortfolioUrl"]) {
    assert.equal(typeof featureIndex[name], "function", name);
  }
  assert.equal(featureIndex.PORTFOLIO_REQUIRED_ACTIVE_CANDIDATES, 3);
  assert.equal(featureIndex.OWNER_PORTFOLIO_ENDPOINT, "/api/owner-research/portfolio");
  assert.equal(featureIndex.DRAFT_RESEARCH_ACTIONS.length, 5);
});

// ----------------------------------------------- static safety guards (TS AST)

const here = path.dirname(fileURLToPath(import.meta.url));
const srcRoot = path.resolve(here, "../src");
const featureRoot = path.join(srcRoot, "features", "owner-research-portfolio");

async function tsFiles(dir) {
  const out = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (entry.name === "node_modules") continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...(await tsFiles(full)));
    else if (/\.(ts|tsx)$/.test(entry.name)) out.push(full);
  }
  return out;
}

async function parsed(files) {
  return Promise.all(
    files.map(async (file) => ({
      file,
      rel: path.relative(featureRoot, file).split(path.sep).join("/"),
      sf: ts.createSourceFile(file, await readFile(file, "utf8"), ts.ScriptTarget.ES2022, true, file.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS),
    })),
  );
}

function walk(node, visit) {
  visit(node);
  ts.forEachChild(node, (child) => walk(child, visit));
}

/** Every module specifier a file pulls in: import/export-from, dynamic import(), require(), import-equals. */
function moduleSpecifiers(sf) {
  const found = [];
  walk(sf, (node) => {
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier) found.push(node.moduleSpecifier.text);
    else if (ts.isImportEqualsDeclaration(node) && ts.isExternalModuleReference(node.moduleReference)) found.push(node.moduleReference.expression.text ?? "<dynamic>");
    else if (ts.isCallExpression(node)) {
      const callee = node.expression;
      const dynamic = callee.kind === ts.SyntaxKind.ImportKeyword;
      const requireCall = ts.isIdentifier(callee) && callee.text === "require";
      if (dynamic || requireCall) found.push(node.arguments[0] && ts.isStringLiteralLike(node.arguments[0]) ? node.arguments[0].text : "<dynamic>");
    }
  });
  return found;
}

const OUTSIDE_ALLOWLIST = [
  /^features\/first-phase-cockpit\/contracts\/firstPhaseEvidencePacket$/,
  /^features\/first-phase-cockpit\/lib\/(freshness|keyboardNav)$/,
  /^features\/first-phase-cockpit\/hooks\/useFirstPhaseEvidenceCockpit$/,
  /^features\/first-phase-cockpit\/fixtures\/demoPacket$/,
  /^lib\/apiBase$/,
];
const ALLOWED_PACKAGES = new Set(["react"]);

test("guard (AST): imports stay inside the feature or an explicit allowlist - no alias, no shared shell/routing/api files", async () => {
  const files = await parsed(await tsFiles(featureRoot));
  assert.ok(files.length >= 20, `feature files found: ${files.length}`);
  for (const { file, rel, sf } of files) {
    for (const specifier of moduleSpecifiers(sf)) {
      assert.notEqual(specifier, "<dynamic>", `${rel}: dynamic module specifier`);
      if (!specifier.startsWith(".")) {
        assert.ok(ALLOWED_PACKAGES.has(specifier), `${rel}: package/alias import '${specifier}' is not allowlisted (aliases like @/ are rejected outright)`);
        continue;
      }
      const resolved = path.resolve(path.dirname(file), specifier);
      const relToSrc = path.relative(srcRoot, resolved).split(path.sep).join("/");
      const inside = relToSrc === "features/owner-research-portfolio" || relToSrc.startsWith("features/owner-research-portfolio/");
      assert.ok(inside || OUTSIDE_ALLOWLIST.some((pattern) => pattern.test(relToSrc)), `${rel}: '${specifier}' resolves to src/${relToSrc}, which is outside the allowlist`);
    }
  }
});

test("guard (AST): read-only - the only network call is one GET in portfolioApi.ts; no mutation, storage or injection sinks", async () => {
  const files = await parsed(await tsFiles(featureRoot));
  const FORBIDDEN = new Set(["XMLHttpRequest", "WebSocket", "EventSource", "localStorage", "sessionStorage", "indexedDB", "useMutation", "eval"]);
  const violations = [];
  for (const { rel, sf } of files) {
    walk(sf, (node) => {
      const where = (label) => violations.push(`${rel}: ${label} @${sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1}`);
      if (ts.isIdentifier(node) && FORBIDDEN.has(node.text)) where(`forbidden identifier ${node.text}`);
      if (ts.isPropertyAccessExpression(node) && ["sendBeacon", "cookie", "fetch"].includes(node.name.text)) where(`forbidden property .${node.name.text}`);
      if (ts.isNewExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === "Function") where("new Function");
      if (ts.isJsxAttribute(node) && node.name.getText(sf) === "dangerouslySetInnerHTML") where("dangerouslySetInnerHTML");
      if ((ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) && /^(post|put|patch|delete)$/i.test(node.text)) where(`mutating verb '${node.text}'`);
      if (ts.isCallExpression(node) && rel !== "lib/portfolioApi.ts") {
        const callee = node.expression;
        const name = ts.isIdentifier(callee) ? callee.text : ts.isPropertyAccessExpression(callee) ? callee.name.text : null;
        if (name === "fetch" || name === "fetchImpl") where(`network call ${name}()`);
      }
    });
  }
  assert.deepEqual(violations, []);

  const api = files.find(({ rel }) => rel === "lib/portfolioApi.ts");
  const calls = [];
  walk(api.sf, (node) => {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === "fetchImpl") calls.push(node);
  });
  assert.equal(calls.length, 1, "exactly one network call site");
  const init = calls[0].arguments[1];
  assert.ok(init && ts.isObjectLiteralExpression(init), "the request options are an object literal");
  const props = Object.fromEntries(init.properties.filter(ts.isPropertyAssignment).map((property) => [property.name.getText(api.sf), property.initializer]));
  assert.equal(props.method?.text, "GET");
  assert.equal("body" in props, false, "a GET never carries a body");
  assert.equal(init.properties.some((property) => ts.isSpreadAssignment(property)), false, "no spread that could smuggle a method or body in");
});

test("guard (AST): no zero-for-missing defaults - no `?? 0`, `|| 0`, `??= 0` or zero default values", async () => {
  const files = await parsed(await tsFiles(featureRoot));
  const isZero = (node) =>
    (ts.isNumericLiteral(node) && Number(node.text) === 0)
    || (ts.isPrefixUnaryExpression(node) && node.operator === ts.SyntaxKind.MinusToken && ts.isNumericLiteral(node.operand) && Number(node.operand.text) === 0)
    || (ts.isParenthesizedExpression(node) && isZero(node.expression));
  const violations = [];
  for (const { rel, sf } of files) {
    walk(sf, (node) => {
      const line = sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1;
      if (ts.isBinaryExpression(node)) {
        const op = node.operatorToken.kind;
        const coalescing = [ts.SyntaxKind.QuestionQuestionToken, ts.SyntaxKind.BarBarToken, ts.SyntaxKind.QuestionQuestionEqualsToken, ts.SyntaxKind.BarBarEqualsToken].includes(op);
        if (coalescing && isZero(node.right)) violations.push(`${rel}:${line} zero default via ${node.operatorToken.getText(sf)}`);
      }
      if ((ts.isParameter(node) || ts.isBindingElement(node)) && node.initializer && isZero(node.initializer)) violations.push(`${rel}:${line} zero default value`);
    });
  }
  assert.deepEqual(violations, []);
});

test("guard: the feature is not mounted by any shared file (tripwire - update MOUNTED_BY when the integration PR lands)", async () => {
  // Mounted in main.tsx as part of the operator research portfolio route.
  const MOUNTED_BY = ["main.tsx"];
  const importers = [];
  for (const file of await tsFiles(srcRoot)) {
    if (file.startsWith(featureRoot + path.sep)) continue;
    const [{ sf }] = await parsed([file]);
    for (const specifier of moduleSpecifiers(sf)) {
      const resolved = specifier.startsWith("@/") ? path.join(srcRoot, specifier.slice(2)) : specifier.startsWith(".") ? path.resolve(path.dirname(file), specifier) : null;
      if (resolved && (resolved === featureRoot || resolved.startsWith(featureRoot + path.sep))) importers.push(path.relative(srcRoot, file).split(path.sep).join("/"));
    }
  }
  assert.deepEqual(importers, MOUNTED_BY);
});
