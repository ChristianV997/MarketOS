/**
 * Owner research portfolio: component tests.
 *
 * The REAL components are rendered with react-dom/server and the resulting DOM
 * is asserted (roles, tab stops, disabled state, aria wiring, escaping, copy).
 * Event-driven keyboard behaviour is verified in a real browser separately; the
 * pure navigation helper it uses is covered by the first-phase cockpit tests.
 */
import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { importSrc } from "./helpers/load-ts.mjs";
import { CTX, FEATURE, NOW, packetWith, portfolioPayload, rankedRow } from "./helpers/owner-research-builders.mjs";

const { OwnerResearchWorkspace } = await importSrc(`${FEATURE}/components/OwnerResearchWorkspace`);
const { describeOption } = await importSrc(`${FEATURE}/components/RankedOpportunityList`);
const { adaptRankingPacket } = await importSrc(`${FEATURE}/lib/adaptRankingReadModel`);
const {
  adaptPortfolioPayload,
  portfolioError,
  portfolioLoading,
  portfolioUnavailable,
} = await importSrc(`${FEATURE}/lib/adaptPortfolioReadModel`);
const { FIXTURE_PORTFOLIO_PAYLOAD, FIXTURE_RANKING_PACKET, FIXTURE_WORKSPACE_ID } = await importSrc(`${FEATURE}/fixtures/ownerResearchFixtures`);
const Page = (await importSrc(`${FEATURE}/OwnerResearchPortfolioPage`)).default;

// ----------------------------------------------------------------- helpers

const ranking = (packet, extra = {}) => adaptRankingPacket({ packet, loading: false, loadError: null, nowMs: NOW, ...extra });
const portfolio = (payload, ctx = CTX) => adaptPortfolioPayload(payload, ctx);
const render = (props) => renderToStaticMarkup(createElement(OwnerResearchWorkspace, props));

const LIVE_ROWS = () => [
  rankedRow("cand-a", { rankIndex: 0, title: "Alpha lamp" }),
  rankedRow("cand-b", { rankIndex: 1, title: "Beta bottle" }),
  rankedRow("cand-c", { rankIndex: 2, title: "Gamma cable" }),
];
const liveRanking = (extra = {}) => ranking(packetWith(LIVE_ROWS(), { fingerprint: { evidenceMode: "live_readonly" } }), extra);

const matches = (html, re) => html.match(re) ?? [];
const optionTags = (html) => matches(html, /<li\b[^>]*role="option"[^>]*>/g);
const draftButtons = (html) => matches(html, /<button\b[^>]*data-draft-action="[^"]*"[^>]*>/g);
const isDisabled = (tag) => /\sdisabled(=""|\s|>)/.test(tag);
const attr = (tag, name) => new RegExp(`\\s${name}="([^"]*)"`).exec(tag)?.[1] ?? null;
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

// Live-looking pair used to prove the enabled path (TEST-ONLY).
const livePair = () => ({ ranking: liveRanking(), portfolio: portfolio(portfolioPayload()) });

// ------------------------------------------------------- fixture / simulation

test("fixture: renders the fixture banner, 2/3 from distinct ids, and keeps draft research disabled", () => {
  const html = render({
    ranking: ranking(FIXTURE_RANKING_PACKET),
    portfolio: portfolio(FIXTURE_PORTFOLIO_PAYLOAD, { expectedWorkspaceId: FIXTURE_WORKSPACE_ID, nowMs: NOW }),
    onDraftResearch: () => {},
  });
  assert.equal(matches(html, /data-qualifier-banner="fixture"/g).length, 1, "one merged fixture banner, not one per scope");
  assert.match(html, /data-qualifier-scopes="ranking portfolio"/, "the banner says it applies to both scopes");
  assert.match(text(html), /Applies to: Ranking and Portfolio/);
  assert.match(text(html), /Fixture \/ simulation data/);
  assert.match(text(html), /not live results/);
  assert.match(html, /data-portfolio-count="2"/);
  assert.match(html, />2\/3</);
  const buttons = draftButtons(html);
  assert.equal(buttons.length, 5);
  assert.ok(buttons.every(isDisabled), "no draft action is enabled for fixture data even with a connected handler");
  assert.match(html, /data-draft-gate="disabled"/);
  assert.match(text(html), /Fixture \/ simulation data cannot enable draft research/);
});

// ---------------------------------------------------- distinct surface states

test("states: loading, error, unavailable and empty ranking each render a distinct banner and no list", () => {
  const cases = [
    ["loading", adaptRankingPacket({ packet: null, loading: true, loadError: null, nowMs: NOW }), /Loading ranked opportunities/, "status"],
    ["error", adaptRankingPacket({ packet: null, loading: false, loadError: "canonical_read_failed", nowMs: NOW }), /Ranking could not be loaded/, "alert"],
    ["unavailable", adaptRankingPacket({ packet: null, loading: false, loadError: null, nowMs: NOW }), /Ranking read model unavailable/, "status"],
    ["empty", ranking(packetWith([])), /No ranked candidates/, "status"],
  ];
  const titles = new Set();
  for (const [phase, model, title, role] of cases) {
    const html = render({ ranking: model, portfolio: portfolio(portfolioPayload()) });
    const banner = matches(html, new RegExp(`<div\\b[^>]*data-state-banner="${phase}"[^>]*>`))[0];
    assert.ok(banner, `${phase}: banner present`);
    assert.equal(attr(banner, "role"), role, `${phase}: role`);
    assert.match(text(html), title, phase);
    assert.equal(optionTags(html).length, 0, `${phase}: no ranked rows are shown`);
    titles.add(text(html).match(title)[0]);
  }
  assert.equal(titles.size, 4, "each state has its own copy");
});

test("states: unavailable and error explain themselves with the backend reason code, unavailable is not empty", () => {
  const unavailable = render({
    ranking: liveRanking(),
    portfolio: portfolioUnavailable("endpoint_not_available", "ws-1"),
  });
  assert.match(text(unavailable), /Portfolio read model unavailable/);
  assert.match(unavailable, /endpoint_not_available/);
  assert.doesNotMatch(text(unavailable), /No active curated candidates/);

  const failed = render({ ranking: liveRanking(), portfolio: portfolioError("http_500", "ws-1") });
  assert.match(text(failed), /Portfolio could not be loaded/);
  assert.match(matches(failed, /<div\b[^>]*data-state-banner="error"[^>]*>/)[0], /role="alert"/);
  assert.match(failed, /http_500/);
});

test("states: an unknown portfolio shows —/3 and never 0/3", () => {
  for (const model of [portfolioLoading("ws-1"), portfolioUnavailable("endpoint_not_available", "ws-1"), portfolioError("http_500", "ws-1"), portfolioUnavailable("workspace_not_selected")]) {
    const html = render({ ranking: liveRanking(), portfolio: model });
    assert.match(html, /data-portfolio-count="unknown"/, model.phase);
    assert.match(html, />—\/3</, model.phase);
    assert.doesNotMatch(html, /(^|[^\d—])0\/3/, `${model.phase} must not read as zero`);
    assert.doesNotMatch(html, /<progress/, `${model.phase}: no progress bar without a count`);
  }
});

test("states: a loaded portfolio with no active candidates is a real 0/3, distinct from unknown", () => {
  const html = render({ ranking: liveRanking(), portfolio: portfolio(portfolioPayload({ items: [], draft_research: { eligible: false } })) });
  assert.match(html, /data-portfolio-count="0"/);
  assert.match(html, />0\/3</);
  assert.match(text(html), /No active curated candidates/);
});

test("states: stale, partial, blocked and fixture banners are distinct and co-occur", () => {
  const each = {
    fixture: packetWith(LIVE_ROWS(), { fingerprint: { evidenceMode: "fixture_only" } }),
    stale: packetWith(LIVE_ROWS(), { state: "stale", fingerprint: { evidenceMode: "live_readonly" } }),
    partial: packetWith(LIVE_ROWS(), { state: "partial", fingerprint: { evidenceMode: "live_readonly" } }),
    blocked: packetWith(LIVE_ROWS(), { state: "blocked", blockedReasons: ["credential_missing"], fingerprint: { evidenceMode: "live_readonly" } }),
  };
  const titles = {
    fixture: /Fixture \/ simulation data/,
    stale: /Stale evidence/,
    partial: /Partial evidence/,
    blocked: /Blocked by backend gates/,
  };
  for (const [qualifier, packet] of Object.entries(each)) {
    const html = render({ ranking: ranking(packet), portfolio: portfolio(portfolioPayload()) });
    const banners = matches(html, /data-qualifier-banner="([a-z]+)"/g).map((match) => /"([a-z]+)"/.exec(match)[1]);
    assert.deepEqual(banners, [qualifier], `${qualifier}: exactly its own banner, no other qualifier`);
    assert.match(html, new RegExp(`data-qualifier-banner="${qualifier}"[^>]*data-qualifier-scopes="ranking"`), `${qualifier}: scoped to ranking only`);
    assert.match(text(html), titles[qualifier], qualifier);
  }
  const combined = render({
    ranking: ranking(packetWith(LIVE_ROWS(), { state: "stale", blockedReasons: ["credential_missing"], fingerprint: { evidenceMode: "fixture_only" } })),
    portfolio: portfolio(portfolioPayload()),
  });
  assert.deepEqual(
    matches(combined, /data-qualifier-banner="([a-z]+)"/g).map((match) => /"([a-z]+)"/.exec(match)[1]),
    ["fixture", "stale"],
    "qualifiers co-occur in a stable order",
  );
  assert.match(combined, /credential_missing/);
});

test("states: blocked gates expand their reason codes by default; ready-with-reasons stays collapsed", () => {
  const blocked = render({
    ranking: ranking(packetWith(LIVE_ROWS(), { state: "blocked", blockedReasons: ["credential_missing"], fingerprint: { evidenceMode: "live_readonly" } })),
    portfolio: portfolio(portfolioPayload()),
  });
  assert.match(blocked, /<details\b[^>]*\sopen(=""|\s|>)/);
  assert.match(blocked, /credential_missing/);

  const partial = render({
    ranking: ranking(packetWith(LIVE_ROWS(), { state: "partial", unavailableReasons: ["consumer_attention_api_unavailable"], fingerprint: { evidenceMode: "live_readonly" } })),
    portfolio: portfolio(portfolioPayload()),
  });
  assert.doesNotMatch(partial, /<details\b[^>]*\sopen(=""|\s|>)/, "advisory reasons are collapsed until asked for");
  assert.match(partial, /consumer_attention_api_unavailable/, "but they remain in the DOM");

  const failed = render({ ranking: liveRanking(), portfolio: portfolioError("http_500", "ws-1") });
  assert.match(failed, /<details\b[^>]*\sopen(=""|\s|>)/, "error reasons are open");
});

test("states: the details summary is a full-height touch target", () => {
  const html = render({ ranking: liveRanking(), portfolio: portfolioUnavailable("endpoint_not_available", "ws-1") });
  assert.match(matches(html, /<summary\b[^>]*>/)[0], /py-3\.5/, "summary padding gives a 44px target");
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
  assert.match(html, /<progress\b[^>]*value="2"[^>]*max="3"/);
  assert.match(text(html), /SKUs, supplier offers, quantities and repeated rows are never counted/);
  assert.match(text(html), /1 repeated row\(s\) for already-counted IDs were ignored/);
  assert.match(text(html), /1 inactive, removed or archived entry is not counted/);
});

test("progress: more than three distinct ids reads honestly (5/3) with the bar clamped", () => {
  const items = ["a", "b", "c", "d", "e"].map((id) => ({ candidate_id: id, status: "active" }));
  const html = render({ ranking: liveRanking(), portfolio: portfolio(portfolioPayload({ items })) });
  assert.match(html, />5\/3</);
  assert.match(html, /<progress\b[^>]*value="3"[^>]*max="3"/);
});

test("progress: malformed entries are reported, never silently counted", () => {
  const html = render({
    ranking: liveRanking(),
    portfolio: portfolio(portfolioPayload({ items: [{ candidate_id: "cand-a", status: "active" }, { candidate_id: " ", status: "active" }, { candidate_id: "cand-b", status: "???" }] })),
  });
  assert.match(html, />1\/3</);
  assert.match(text(html), /1 entry with a missing or malformed candidate ID was ignored/);
  assert.match(text(html), /1 entry with an unknown status was ignored/);
  assert.match(html, /data-qualifier-banner="partial"/);
});

test("progress: portfolio ids outside the current ranking are flagged, ranked ids in the portfolio are marked", () => {
  const html = render({
    ranking: liveRanking(),
    portfolio: portfolio(portfolioPayload({ items: [{ candidate_id: "cand-a", status: "active" }, { candidate_id: "legacy-only", status: "active" }] })),
  });
  assert.match(text(html), /legacy-only \(not in current ranking\)/);
  assert.match(text(html), /Alpha lamp/);
  const alphaOption = optionTags(html).find((tag) => attr(tag, "data-candidate-id") === "cand-a");
  assert.match(attr(alphaOption, "aria-label"), /in curated portfolio/);
  const betaOption = optionTags(html).find((tag) => attr(tag, "data-candidate-id") === "cand-b");
  assert.doesNotMatch(attr(betaOption, "aria-label"), /in curated portfolio/);
});

// ----------------------------------------------------------- draft research

test("draft research: all five actions are native-disabled unless the backend explicitly reports eligibility", () => {
  const scenarios = {
    "three ids but eligibility not reported": portfolioPayload({ draft_research: undefined }),
    "backend says not eligible": portfolioPayload({ draft_research: { eligible: false, reasons: ["supplier_gate_open"] } }),
    "eligibility is a string": portfolioPayload({ draft_research: { eligible: "true" } }),
    "eligible but only two ids": portfolioPayload({ items: [{ candidate_id: "cand-a", status: "active" }, { candidate_id: "cand-b", status: "active" }] }),
  };
  for (const [name, payload] of Object.entries(scenarios)) {
    const html = render({ ranking: liveRanking(), portfolio: portfolio(payload), onDraftResearch: () => {} });
    const buttons = draftButtons(html);
    assert.equal(buttons.length, 5, name);
    assert.ok(buttons.every(isDisabled), `${name}: every action disabled`);
    assert.match(html, /data-draft-gate="disabled"/, name);
    assert.match(html, /id="owner-draft-reasons"/, `${name}: reasons are visible`);
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
  assert.doesNotMatch(html, /id="owner-draft-reasons"/);
  assert.match(text(html), /Backend reports eligible for draft research/);
  assert.deepEqual(
    buttons.map((tag) => attr(tag, "data-draft-action")),
    ["target_markets", "personas", "brand_ad_strategy", "social_channels", "storefront_landing"],
  );
});

test("draft research: eligibility without a connected service stays disabled and says so", () => {
  const { ranking: liveRank, portfolio: livePort } = livePair();
  const html = render({ ranking: liveRank, portfolio: livePort });
  assert.ok(draftButtons(html).every(isDisabled));
  assert.match(text(html), /No draft-research service is connected to this page yet/);
});

test("draft research: every button is a real type=button and the group is labelled and described", () => {
  const html = render({ ranking: liveRanking(), portfolio: portfolio(portfolioPayload({ draft_research: undefined })) });
  assert.ok(draftButtons(html).every((tag) => attr(tag, "type") === "button"));
  const group = matches(html, /<div\b[^>]*role="group"[^>]*>/)[0];
  assert.equal(attr(group, "aria-labelledby"), "owner-draft-heading");
  assert.equal(attr(group, "aria-describedby"), "owner-draft-reasons");
});

// ------------------------------------------------- ranked list: semantics + a11y

test("list: backend order, one option per candidate, a single tab stop on the selected option", () => {
  const html = render({ ranking: liveRanking(), portfolio: portfolio(portfolioPayload()) });
  const options = optionTags(html);
  assert.deepEqual(options.map((tag) => attr(tag, "data-candidate-id")), ["cand-a", "cand-b", "cand-c"]);
  assert.deepEqual(options.map((tag) => attr(tag, "aria-selected")), ["true", "false", "false"]);
  assert.deepEqual(options.map((tag) => attr(tag, "tabindex")), ["0", "-1", "-1"]);
  assert.ok(options.every((tag) => attr(tag, "aria-label")), "each option has an accessible name");
  const listbox = matches(html, /<ul\b[^>]*role="listbox"[^>]*>/)[0];
  assert.equal(attr(listbox, "aria-labelledby"), "owner-ranked-heading");
  assert.equal(attr(listbox, "aria-describedby"), "owner-ranked-hint");
  assert.equal(attr(listbox, "aria-orientation"), "vertical");
});

test("list: initialSelectedId moves the tab stop and the detail panel; unknown ids fall back to the first row", () => {
  const props = { ranking: liveRanking(), portfolio: portfolio(portfolioPayload()) };
  const second = render({ ...props, initialSelectedId: "cand-b" });
  assert.deepEqual(optionTags(second).map((tag) => attr(tag, "tabindex")), ["-1", "0", "-1"]);
  assert.match(second, /Candidate ID: cand-b/);

  const fallback = render({ ...props, initialSelectedId: "does-not-exist" });
  assert.deepEqual(optionTags(fallback).map((tag) => attr(tag, "tabindex")), ["0", "-1", "-1"]);
  assert.match(fallback, /Candidate ID: cand-a/);
});

test("list: the screen-reader label carries rank, id, evidence, portfolio membership and freshness", () => {
  const model = markMembership(liveRanking().rows, ["cand-a"]);
  const label = describeOption(model[0]);
  assert.match(label, /^Rank 1, Alpha lamp, candidate cand-a, evidence /);
  assert.match(label, /in curated portfolio/);
  assert.match(label, /freshness not reported|fresh|stale/);
});

function markMembership(rows, activeIds) {
  return rows.map((row) => ({ ...row, inPortfolio: activeIds.includes(row.candidateId) }));
}

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

test("a11y: state is never colour-only - every chip and banner carries text", () => {
  const html = render({ ranking: ranking(FIXTURE_RANKING_PACKET), portfolio: portfolio(FIXTURE_PORTFOLIO_PAYLOAD, { expectedWorkspaceId: FIXTURE_WORKSPACE_ID, nowMs: NOW }) });
  assert.match(text(html), /Evidence: /);
  assert.match(text(html), /Partial evidence/);
  assert.match(text(html), /Freshness not reported|Fresh|Stale/);
  assert.match(html, /aria-label="Ranking run provenance"/);
});

// ------------------------------------------------------------- detail panel

test("detail: null scores read Not reported, never 0%", () => {
  const cells = rankedRow("solo").pillarCells.map((cell) => ({ ...cell, score: null, detail: null }));
  const model = ranking(packetWith([rankedRow("solo", { title: "Solo", evidenceCompleteness: null, confidence: null, pillarCells: cells, missingEvidence: [], hardGates: [], conflicts: [], assumptions: [], evidenceReferences: [], replayIdentity: null })]));
  const html = render({ ranking: model, portfolio: portfolio(portfolioPayload()) });
  const detail = html.slice(html.indexOf('id="owner-opportunity-detail"'));
  assert.doesNotMatch(detail, /\b0%/, "no zero percentages for missing values");
  assert.match(text(detail), /Evidence completeness Not reported/);
  assert.match(text(detail), /Confidence Not reported/);
  assert.match(text(detail), /No evidence gaps were reported by the backend/);
  assert.match(text(detail), /No evidence references were reported/);
  assert.match(text(detail), /Replay identity Not reported/);
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
    ]),
  );
  const html = render({ ranking: model, portfolio: portfolio(portfolioPayload()) });
  const detail = html.slice(html.indexOf('id="owner-opportunity-detail"'));
  const pillarList = matches(detail, /<ul\b[^>]*aria-label="Evidence pillars for Alpha lamp, exactly as reported"[^>]*>/)[0];
  assert.ok(pillarList, "pillars are a labelled list");
  const pillarItems = matches(detail, /<li\b[^>]*data-pillar="[a-z_]+"[^>]*>/g);
  assert.equal(pillarItems.length, 6, "one item per reported pillar");
  assert.match(text(detail), /Market Status: partial Reported score: 58%/);
  assert.match(text(detail), /Attention Status: unavailable Reported score: Not reported/);
  assert.doesNotMatch(detail, /<table\b/, "no table: it forced a horizontal scroll region that keyboards cannot reach");
  assert.doesNotMatch(detail, /overflow-x-auto|overflow-auto|overflow-scroll/, "no scroll region inside the detail panel");
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
  const hostile = '<script>alert(1)</script>';
  const model = ranking(
    packetWith([
      rankedRow('id"><img src=x onerror=alert(1)>', { title: hostile }),
      rankedRow("cand-safe", { title: `${hostile} & <b>bold</b>`, missingEvidence: [hostile], evidenceReferences: [`javascript:alert(1)`] }),
    ]),
  );
  const html = render({ ranking: model, portfolio: portfolio(portfolioPayload()) });
  assert.doesNotMatch(html, /<script/i);
  assert.doesNotMatch(html, /<img/i);
  assert.doesNotMatch(html, /<b>bold/i);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<a\b[^>]*href="javascript:/i, "evidence references are text, never links");
});

// ---------------------------------------------------------------- page

test("page: fixture source renders labelled fixture data without a window or network", () => {
  const html = renderToStaticMarkup(createElement(Page, { source: "fixture" }));
  assert.match(html, /data-owner-research-workspace/);
  assert.match(html, /data-qualifier-banner="fixture"/);
  assert.ok(draftButtons(html).every(isDisabled));
});

test("page: exports a default component and mounts nothing by itself", async () => {
  assert.equal(typeof Page, "function");
});

// ------------------------------------------------- static safety guards

const featureRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/features/owner-research-portfolio");

async function featureSources() {
  const out = [];
  async function walk(dir) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) await walk(full);
      else if (/\.(ts|tsx)$/.test(entry.name)) out.push([path.relative(featureRoot, full), await readFile(full, "utf8")]);
    }
  }
  await walk(featureRoot);
  return out;
}

test("guard: read-only - the only network call is a GET in portfolioApi.ts", async () => {
  const sources = await featureSources();
  assert.ok(sources.length >= 15);
  for (const [file, source] of sources) {
    const code = source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    assert.doesNotMatch(code, /\b(POST|PUT|PATCH|DELETE)\b/, `${file}: no mutating HTTP verb`);
    assert.doesNotMatch(code, /\b(XMLHttpRequest|WebSocket|EventSource|sendBeacon)\b/, `${file}: no other transport`);
    assert.doesNotMatch(code, /\b(localStorage|sessionStorage|indexedDB)\b/, `${file}: no client persistence`);
    assert.doesNotMatch(code, /dangerouslySetInnerHTML|\beval\(|new Function\(/, `${file}: no injection sinks`);
    if (file !== path.join("lib", "portfolioApi.ts")) {
      assert.doesNotMatch(code, /\bfetch\s*\(|fetchImpl\s*\(/, `${file}: only portfolioApi.ts may call fetch`);
    }
  }
  const api = sources.find(([file]) => file === path.join("lib", "portfolioApi.ts"))[1];
  assert.match(api, /method: "GET"/);
  assert.match(api, /from "\.\.\/\.\.\/\.\.\/lib\/apiBase"/, "API origin comes from apiBase.ts");
  assert.doesNotMatch(api, /import\.meta\.env|VITE_/, "no env access of its own");
});

test("guard: no zero-for-missing defaults anywhere in the feature", async () => {
  for (const [file, source] of await featureSources()) {
    const code = source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    assert.doesNotMatch(code, /(\?\?|\|\|)\s*0(?![.\d])/, `${file}: '?? 0' / '|| 0' would turn missing into zero`);
    assert.doesNotMatch(code, /=\s*0\s*\)\s*=>/, `${file}: no zero default parameters for metrics`);
  }
});

test("guard: isolated - no shared routing, shell, sidebar or API-client files are imported or edited", async () => {
  const forbidden = /(Sidebar|Shell|PhaseHeader|\/main|\/App|lib\/api"|canonicalEventsApi|useCanonicalEvents"|posthog)/;
  const allowedCrossFeature = /first-phase-cockpit\/(contracts|lib|hooks|fixtures)\//;
  for (const [file, source] of await featureSources()) {
    for (const specifier of matches(source, /from\s+"([^"]+)"/g).map((match) => /"([^"]+)"/.exec(match)[1])) {
      if (!specifier.startsWith(".")) continue;
      assert.doesNotMatch(specifier, forbidden, `${file}: ${specifier}`);
      if (specifier.includes("features/") || /\.\.\/first-phase-cockpit/.test(specifier) || /\.\.\/\.\.\/first-phase-cockpit/.test(specifier)) {
        assert.match(specifier, allowedCrossFeature, `${file}: unexpected cross-feature import ${specifier}`);
      }
    }
  }
});
