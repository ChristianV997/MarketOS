/**
 * Owner research portfolio: adapter + API-contract tests.
 *
 * These import the REAL modules (via tests/helpers/ts-hooks.mjs); nothing here
 * re-implements production logic. Live-looking payloads below are TEST-ONLY
 * shapes used to prove the gate; they are not fixtures shipped to the UI.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { importSrc } from "./helpers/load-ts.mjs";
import { CTX, FEATURE, NOW, packetWith, portfolioPayload, rankedRow } from "./helpers/owner-research-builders.mjs";

const { adaptRankingPacket, markPortfolioMembership } = await importSrc(`${FEATURE}/lib/adaptRankingReadModel`);
const {
  adaptPortfolioPayload,
  evaluateDraftResearchGate,
  parseEvidenceMode,
  portfolioError,
  portfolioLoading,
  portfolioUnavailable,
  resultToPortfolioModel,
  scanForSecretKeys,
} = await importSrc(`${FEATURE}/lib/adaptPortfolioReadModel`);
const { resolveListboxKey } = await importSrc(`${FEATURE}/lib/listboxKeys`);
const { announceSurface } = await importSrc(`${FEATURE}/lib/announce`);
const { buildPortfolioUrl, fetchOwnerPortfolioPayload, MAX_PORTFOLIO_RESPONSE_CHARS } = await importSrc(`${FEATURE}/lib/portfolioApi`);
const { isStableCandidateId } = await importSrc(`${FEATURE}/lib/candidateId`);
const { describeFreshness } = await importSrc(`${FEATURE}/lib/freshnessView`);
const { formatReportedScore, NOT_REPORTED } = await importSrc(`${FEATURE}/lib/format`);
const contracts = await importSrc(`${FEATURE}/contracts/ownerResearch`);
const stateCopy = await importSrc(`${FEATURE}/lib/stateCopy`);

// ---------------------------------------------------------------- builders

const adaptRanking = (packet, extra = {}) =>
  adaptRankingPacket({ packet, loading: false, loadError: null, nowMs: NOW, ...extra });

const adaptPortfolio = (payload, ctx = CTX) => adaptPortfolioPayload(payload, ctx);

// ------------------------------------------------------------ contract shape

test("contract: portfolio requirement is exactly three and the proposed endpoint is a read path", () => {
  assert.equal(contracts.PORTFOLIO_REQUIRED_ACTIVE_CANDIDATES, 3);
  assert.equal(contracts.OWNER_PORTFOLIO_SCHEMA_VERSION, "owner-research-portfolio-v1");
  assert.equal(contracts.OWNER_PORTFOLIO_ENDPOINT, "/api/owner-research/portfolio");
  assert.deepEqual(
    contracts.DRAFT_RESEARCH_ACTIONS.map((action) => action.id),
    ["target_markets", "personas", "brand_ad_strategy", "social_channels", "storefront_landing"],
  );
});

// ------------------------------------------------------------- candidate id

test("candidate id: exact opaque identity, never normalised", () => {
  for (const good of ["cand-1", "A", "a", "SKU-990-REC", "x".repeat(128)]) {
    assert.equal(isStableCandidateId(good), true, good);
  }
  for (const bad of ["", " ", " cand-1", "cand-1 ", "\tcand", "a\nb", "x".repeat(129), null, undefined, 7, {}, []]) {
    assert.equal(isStableCandidateId(bad), false, JSON.stringify(bad));
  }
});

// ------------------------------------------------------- portfolio counting

test("portfolio: X/3 counts distinct active candidate ids only", () => {
  const model = adaptPortfolio(
    portfolioPayload({
      items: [
        { candidate_id: "cand-a", status: "active" },
        { candidate_id: "cand-b", status: "active" },
      ],
    }),
  );
  assert.equal(model.phase, "ready");
  assert.equal(model.activeCount, 2);
  assert.equal(model.required, 3);
  assert.deepEqual(model.activeCandidateIds, ["cand-a", "cand-b"]);
});

test("portfolio: SKUs, supplier offers, quantities and repeated rows never add to the count", () => {
  const model = adaptPortfolio(
    portfolioPayload({
      items: [
        { candidate_id: "cand-a", status: "active", sku: "SKU-1", supplier_offer_count: 9, quantity: 500 },
        { candidate_id: "cand-a", status: "active", sku: "SKU-2", supplier_offer_count: 4, quantity: 30 },
        { candidate_id: "cand-a", status: "active", sku: "SKU-3" },
        { candidate_id: "cand-b", status: "active", quantity: 10000 },
      ],
    }),
  );
  assert.equal(model.activeCount, 2);
  assert.deepEqual(model.activeCandidateIds, ["cand-a", "cand-b"]);
  assert.equal(model.ignored.duplicateActiveRows, 2);
});

test("portfolio: one huge-quantity, many-SKU candidate is still 1/3", () => {
  const items = Array.from({ length: 40 }, (_, index) => ({
    candidate_id: "solo",
    status: "active",
    sku: `SKU-${index}`,
    quantity: 1000 + index,
    supplier_offer_count: index + 1,
  }));
  const model = adaptPortfolio(portfolioPayload({ items }));
  assert.equal(model.activeCount, 1);
  assert.equal(model.ignored.duplicateActiveRows, 39);
});

test("portfolio: inactive, removed and archived entries are not active", () => {
  const model = adaptPortfolio(
    portfolioPayload({
      items: [
        { candidate_id: "cand-a", status: "active" },
        { candidate_id: "cand-b", status: "inactive" },
        { candidate_id: "cand-c", status: "removed" },
        { candidate_id: "cand-d", status: "archived" },
      ],
    }),
  );
  assert.equal(model.activeCount, 1);
  assert.equal(model.ignored.notActive, 3);
  assert.equal(model.qualifiers.includes("partial"), false, "expected lifecycle states are not partial evidence");
});

test("portfolio: identity is exact - case variants are distinct ids", () => {
  const model = adaptPortfolio(
    portfolioPayload({ items: [{ candidate_id: "Cand-A", status: "active" }, { candidate_id: "cand-a", status: "active" }] }),
  );
  assert.equal(model.activeCount, 2);
});

test("portfolio: malformed ids and statuses are ignored and flagged partial, never counted", () => {
  const model = adaptPortfolio(
    portfolioPayload({
      items: [
        { candidate_id: "cand-a", status: "active" },
        { candidate_id: "", status: "active" },
        { candidate_id: "  cand-b  ", status: "active" },
        { candidate_id: 42, status: "active" },
        { status: "active" },
        { candidate_id: "cand-c", status: "ACTIVE" },
        { candidate_id: "cand-d" },
        "not-an-object",
        null,
      ],
    }),
  );
  assert.equal(model.activeCount, 1);
  assert.deepEqual(model.activeCandidateIds, ["cand-a"]);
  assert.equal(model.ignored.invalidId, 4);
  assert.equal(model.ignored.unknownStatus, 2);
  assert.equal(model.ignored.malformedEntries, 2);
  assert.ok(model.qualifiers.includes("partial"));
});

test("portfolio: identity is never derived from a title or SKU", () => {
  const model = adaptPortfolio(
    portfolioPayload({ items: [{ title: "Portable espresso maker", sku: "FIX-ESP-01", status: "active" }] }),
  );
  assert.equal(model.activeCount, 0);
  assert.equal(model.phase, "empty");
  assert.equal(model.ignored.invalidId, 1);
});

test("portfolio: more than three distinct ids reports the real count, progress is not clamped in the model", () => {
  const items = ["a", "b", "c", "d", "e"].map((id) => ({ candidate_id: id, status: "active" }));
  assert.equal(adaptPortfolio(portfolioPayload({ items })).activeCount, 5);
});

test("portfolio: a loaded portfolio with no active entries is empty (0), distinct from unknown (null)", () => {
  const empty = adaptPortfolio(portfolioPayload({ items: [] }));
  assert.equal(empty.phase, "empty");
  assert.equal(empty.activeCount, 0);

  for (const unknown of [portfolioLoading("ws-1"), portfolioUnavailable("endpoint_not_available", "ws-1"), portfolioError("http_500", "ws-1")]) {
    assert.equal(unknown.activeCount, null, `${unknown.phase} must not read as zero`);
    assert.deepEqual(unknown.activeCandidateIds, []);
  }
});

// -------------------------------------------------- portfolio fail-closed input

test("portfolio: rejects unsafe or foreign payloads without rendering a count", () => {
  const cases = [
    [null, "portfolio_payload_not_object"],
    [[], "portfolio_payload_not_object"],
    [portfolioPayload({ schema_version: "owner-research-portfolio-v2" }), "unsupported_schema_version"],
    [portfolioPayload({ read_only: false }), "mutation_authority_rejected"],
    [portfolioPayload({ mutated: true }), "mutation_authority_rejected"],
    [portfolioPayload({ read_only: undefined }), "mutation_authority_rejected"],
    [portfolioPayload({ workspace_id: "" }), "workspace_id_missing"],
    [portfolioPayload({ workspace_id: "ws-OTHER" }), "workspace_mismatch"],
    [portfolioPayload({ items: "nope" }), "items_not_array"],
    [portfolioPayload({ items: new Array(501).fill({ candidate_id: "x", status: "active" }) }), "items_exceed_limit"],
    [portfolioPayload({ meta: { api_key: "abc" } }), "secret_shaped_field_rejected"],
    [portfolioPayload({ items: [{ candidate_id: "a", status: "active", auth_token: "t" }] }), "secret_shaped_field_rejected"],
  ];
  for (const [payload, reason] of cases) {
    const model = adaptPortfolio(payload);
    assert.equal(model.phase, "error", reason);
    assert.deepEqual(model.reasons, [reason]);
    assert.equal(model.activeCount, null, `${reason} must not yield a count`);
  }
});

test("portfolio: no selected workspace is unavailable, not an ambient default tenant", () => {
  for (const expectedWorkspaceId of [null, "", "   "]) {
    const model = adaptPortfolioPayload(portfolioPayload(), { expectedWorkspaceId, nowMs: NOW });
    assert.equal(model.phase, "unavailable");
    assert.deepEqual(model.reasons, ["workspace_not_selected"]);
    assert.equal(model.activeCount, null);
  }
});

// --------------------------------------------------- provenance and freshness

test("portfolio: evidence mode parsing never upgrades fixture-like values to live", () => {
  assert.equal(parseEvidenceMode("live_readonly"), "live_readonly");
  assert.equal(parseEvidenceMode("fixture_demo"), "fixture_only");
  assert.equal(parseEvidenceMode("live_readonly_fixture"), "fixture_only");
  assert.equal(parseEvidenceMode("simulated_live"), "simulated");
  assert.equal(parseEvidenceMode("manual_import"), "manual");
  for (const value of ["live", "LIVE", "production", "", null, undefined, 3]) {
    assert.equal(parseEvidenceMode(value), "unknown", String(value));
  }
});

test("portfolio: fixture and stale payloads are qualified, not presented as live", () => {
  const fixture = adaptPortfolio(portfolioPayload({ evidence_mode: "fixture_only" }));
  assert.ok(fixture.qualifiers.includes("fixture"));

  const expired = adaptPortfolio(portfolioPayload({ expires_at: "2026-09-29T11:59:00Z" }));
  assert.ok(expired.qualifiers.includes("stale"));
  assert.equal(expired.freshness.status, "stale");

  const old = adaptPortfolio(portfolioPayload({ generated_at: "2026-09-25T00:00:00Z" }));
  assert.ok(old.qualifiers.includes("stale"));

  const unreported = adaptPortfolio(portfolioPayload({ generated_at: undefined }));
  assert.equal(unreported.freshness.status, "not_reported");
  assert.equal(unreported.qualifiers.includes("stale"), false);
});

test("freshness: never invents a timestamp", () => {
  assert.equal(describeFreshness({ nowMs: NOW }).status, "not_reported");
  assert.equal(describeFreshness({ generatedAt: "not-a-date", nowMs: NOW }).status, "invalid");
  assert.equal(describeFreshness({ expiresAt: "also-bad", nowMs: NOW }).status, "invalid");
  assert.equal(describeFreshness({ expiresAt: "2026-09-30T00:00:00Z", nowMs: NOW }).status, "fresh");
  assert.equal(describeFreshness({ expiresAt: "2026-09-29T11:00:00Z", nowMs: NOW }).status, "stale");
  assert.equal(describeFreshness({ generatedAt: "2026-09-29T11:30:00Z", nowMs: NOW }).status, "fresh");
});

// ---------------------------------------------- eligibility and the draft gate

test("eligibility: only a strict boolean from the backend counts as reported", () => {
  for (const draft of [undefined, null, {}, { eligible: "true" }, { eligible: 1 }, { eligible: null }, "yes"]) {
    const model = adaptPortfolio(portfolioPayload({ draft_research: draft }));
    assert.equal(model.eligibility.reported, false, JSON.stringify(draft));
    assert.equal(model.eligibility.eligible, false);
  }
  const yes = adaptPortfolio(portfolioPayload({ draft_research: { eligible: true } }));
  assert.deepEqual([yes.eligibility.reported, yes.eligibility.eligible], [true, true]);
  const no = adaptPortfolio(portfolioPayload({ draft_research: { eligible: false, reasons: ["need_more_evidence", 7, ""] } }));
  assert.deepEqual([no.eligibility.reported, no.eligibility.eligible], [true, false]);
  assert.deepEqual(no.eligibility.reasons, ["need_more_evidence"]);
});

test("gate: enabled only when the backend explicitly reports eligible, provenance is known and a handler is connected", () => {
  const ok = evaluateDraftResearchGate(adaptPortfolio(portfolioPayload()), { handlerConnected: true });
  assert.deepEqual(ok, { enabled: true, reasons: [] });
});

test("gate: three distinct active candidates alone never enable draft research", () => {
  const model = adaptPortfolio(portfolioPayload({ draft_research: undefined }));
  assert.equal(model.activeCount, 3);
  const gate = evaluateDraftResearchGate(model, { handlerConnected: true });
  assert.equal(gate.enabled, false);
  assert.ok(gate.reasons.some((reason) => /has not reported draft-research eligibility/.test(reason)));
});

test("gate: backend not-eligible wins even with three active candidates, and its reasons are surfaced", () => {
  const model = adaptPortfolio(portfolioPayload({ draft_research: { eligible: false, reasons: ["supplier_gate_open"] } }));
  const gate = evaluateDraftResearchGate(model, { handlerConnected: true });
  assert.equal(gate.enabled, false);
  assert.ok(gate.reasons.includes("supplier_gate_open"));
});

test("gate: eligible=true with fewer than three distinct active ids conflicts and stays disabled", () => {
  const model = adaptPortfolio(
    portfolioPayload({ items: [{ candidate_id: "a", status: "active", quantity: 99 }, { candidate_id: "a", status: "active" }] }),
  );
  assert.equal(model.eligibility.conflict, true);
  const gate = evaluateDraftResearchGate(model, { handlerConnected: true });
  assert.equal(gate.enabled, false);
  assert.ok(gate.reasons.some((reason) => /conflicts with the distinct active candidate count \(1\/3\)/.test(reason)));
});

test("gate: fixture, simulated, stale and unknown-provenance portfolios stay disabled even if eligible", () => {
  for (const [overrides, pattern] of [
    [{ evidence_mode: "fixture_only" }, /Fixture \/ simulation/],
    [{ evidence_mode: "simulated" }, /Fixture \/ simulation/],
    [{ expires_at: "2026-09-01T00:00:00Z" }, /stale/],
    [{ evidence_mode: "mystery" }, /provenance is not reported/],
  ]) {
    const gate = evaluateDraftResearchGate(adaptPortfolio(portfolioPayload(overrides)), { handlerConnected: true });
    assert.equal(gate.enabled, false, JSON.stringify(overrides));
    assert.ok(gate.reasons.some((reason) => pattern.test(reason)), JSON.stringify(gate.reasons));
  }
});

test("gate: no connected handler keeps actions disabled and says why", () => {
  const gate = evaluateDraftResearchGate(adaptPortfolio(portfolioPayload()), { handlerConnected: false });
  assert.equal(gate.enabled, false);
  assert.deepEqual(gate.reasons, ["No draft-research service is connected to this page yet."]);
});

test("gate: loading, error and unavailable portfolios are disabled", () => {
  for (const model of [portfolioLoading("ws-1"), portfolioError("http_500", "ws-1"), portfolioUnavailable("endpoint_not_available", "ws-1")]) {
    const gate = evaluateDraftResearchGate(model, { handlerConnected: true });
    assert.equal(gate.enabled, false, model.phase);
    assert.ok(gate.reasons.length >= 1);
  }
});

// -------------------------------------------------------------------- ranking

test("ranking: preserves backend order and never re-sorts by score", () => {
  const rows = [
    rankedRow("low-score-first", { rankIndex: 0, supplierScore: 0.1, competitionScore: 0.1 }),
    rankedRow("high-score-second", { rankIndex: 1, supplierScore: 0.99, competitionScore: 0.99 }),
    rankedRow("mid-third", { rankIndex: 2, supplierScore: 0.5, competitionScore: 0.5 }),
  ];
  const model = adaptRanking(packetWith(rows));
  assert.equal(model.phase, "ready");
  assert.deepEqual(model.rows.map((row) => row.candidateId), ["low-score-first", "high-score-second", "mid-third"]);
  assert.deepEqual(model.rows.map((row) => row.rankNumber), [1, 2, 3]);
});

test("ranking: missing values stay null and never become zero", () => {
  const cells = rankedRow("x").pillarCells.map((cell) => ({ ...cell, score: null, detail: null }));
  const model = adaptRanking(packetWith([rankedRow("x", { evidenceCompleteness: null, confidence: null, pillarCells: cells })]));
  const [row] = model.rows;
  assert.equal(row.evidenceCompleteness, null);
  assert.equal(row.confidence, null);
  assert.ok(row.pillars.length > 0);
  for (const pillar of row.pillars) assert.equal(pillar.score, null);
  assert.equal(formatReportedScore(null), NOT_REPORTED);
  assert.equal(formatReportedScore(undefined), NOT_REPORTED);
  assert.equal(formatReportedScore(Number.NaN), NOT_REPORTED);
  assert.equal(formatReportedScore(0), "0%", "an explicit reported zero is still shown as zero");
  assert.equal(formatReportedScore(0.615), "62%");
  assert.match(formatReportedScore(72), /outside 0-1/);
});

test("ranking: duplicate and malformed ids are dropped, flagged partial, and never re-keyed from title or SKU", () => {
  const rows = [
    rankedRow("cand-a", { rankIndex: 0, title: "First" }),
    rankedRow("cand-a", { rankIndex: 1, title: "Duplicate of first" }),
    rankedRow("", { rankIndex: 2, title: "Blank id", sku: "SKU-BLANK" }),
    rankedRow(" cand-b ", { rankIndex: 3, title: "Padded id" }),
    rankedRow("cand-c", { rankIndex: 4, title: "Third" }),
  ];
  const model = adaptRanking(packetWith(rows));
  assert.deepEqual(model.rows.map((row) => row.candidateId), ["cand-a", "cand-c"]);
  assert.equal(model.rows[0].title, "First", "the first occurrence wins");
  assert.deepEqual(model.dropped.map((item) => item.reason), ["duplicate_candidate_id", "invalid_candidate_id", "invalid_candidate_id"]);
  assert.ok(model.qualifiers.includes("partial"));
  assert.ok(model.warnings.includes("duplicate_candidate_id:cand-a"));
});

test("ranking: an inconsistent rankIndex is surfaced, not repaired", () => {
  const rows = [rankedRow("a", { rankIndex: 2 }), rankedRow("b", { rankIndex: 1 }), rankedRow("c", { rankIndex: Number.NaN })];
  const model = adaptRanking(packetWith(rows));
  assert.deepEqual(model.rows.map((row) => row.candidateId), ["a", "b", "c"]);
  assert.deepEqual(model.rows.map((row) => row.rankNumber), [3, 2, null]);
  assert.ok(model.warnings.includes("rank_order_inconsistent:b"));
  assert.ok(model.warnings.includes("rank_index_invalid:c"));
  assert.ok(model.qualifiers.includes("partial"));
});

test("ranking: distinct phases for loading, error, unavailable and empty", () => {
  assert.equal(adaptRankingPacket({ packet: null, loading: true, loadError: null, nowMs: NOW }).phase, "loading");
  assert.equal(adaptRanking(packetWith([], { state: "loading" })).phase, "loading");

  const missing = adaptRankingPacket({ packet: null, loading: false, loadError: null, nowMs: NOW });
  assert.equal(missing.phase, "unavailable");
  assert.deepEqual(missing.reasons, ["ranking_read_model_not_provided"]);

  const failed = adaptRankingPacket({ packet: null, loading: false, loadError: "canonical_read_failed", nowMs: NOW });
  assert.equal(failed.phase, "error");

  const unavailable = adaptRanking(packetWith([rankedRow("hidden")], { state: "unavailable", unavailableReasons: ["endpoint_down"] }));
  assert.equal(unavailable.phase, "unavailable");
  assert.deepEqual(unavailable.rows, [], "rows from an unavailable read model are never shown");
  assert.deepEqual(unavailable.reasons, ["endpoint_down"]);

  const empty = adaptRanking(packetWith([]));
  assert.equal(empty.phase, "empty");
  assert.deepEqual(empty.rows, []);
});

test("ranking: a hard read failure with no rows is an error; with rows it is partial", () => {
  const noRows = adaptRanking(packetWith([], { state: "unavailable" }), { loadError: "canonical_read_failed" });
  assert.equal(noRows.phase, "error");
  const withRows = adaptRanking(packetWith([rankedRow("a")]), { loadError: "canonical_read_failed" });
  assert.equal(withRows.phase, "ready");
  assert.ok(withRows.qualifiers.includes("partial"));
  assert.ok(withRows.reasons.includes("canonical_read_failed"));
});

test("ranking: fixture, simulated, stale, partial and blocked qualifiers are distinct and can co-occur", () => {
  const rows = [rankedRow("a")];
  assert.deepEqual(adaptRanking(packetWith(rows, { fingerprint: { evidenceMode: "fixture_only" } })).qualifiers, ["fixture"]);
  assert.deepEqual(adaptRanking(packetWith(rows, { fingerprint: { evidenceMode: "simulated" } })).qualifiers, ["fixture"]);
  assert.deepEqual(adaptRanking(packetWith(rows, { fingerprint: { evidenceMode: "live_readonly" } })).qualifiers, []);
  assert.deepEqual(adaptRanking(packetWith(rows, { fingerprint: { evidenceMode: "manual" } })).qualifiers, []);
  assert.deepEqual(adaptRanking(packetWith(rows, { state: "stale", fingerprint: { evidenceMode: "live_readonly" } })).qualifiers, ["stale"]);
  assert.deepEqual(adaptRanking(packetWith(rows, { state: "partial", fingerprint: { evidenceMode: "live_readonly" } })).qualifiers, ["partial"]);
  assert.deepEqual(adaptRanking(packetWith(rows, { state: "blocked", fingerprint: { evidenceMode: "live_readonly" } })).qualifiers, ["blocked"]);
  const all = adaptRanking(packetWith(rows, { state: "stale", blockedReasons: ["credential_missing"], fingerprint: { evidenceMode: "fixture_only" } }));
  assert.deepEqual(all.qualifiers, ["fixture", "stale"]);
  assert.ok(all.reasons.includes("credential_missing"));
});

test("ranking: refuses a read model that is not read-only", () => {
  const model = adaptRanking(packetWith([rankedRow("a")], { fingerprint: { readOnly: false } }));
  assert.equal(model.phase, "error");
  assert.deepEqual(model.reasons, ["ranking_read_model_not_read_only"]);
  assert.deepEqual(model.rows, []);
});

test("ranking: freshness is computed from what is reported, and unreported stays unreported", () => {
  const unreported = adaptRanking(packetWith([rankedRow("a", { freshnessExpiry: null })], { fingerprint: { generatedAt: null, freshnessLabel: null } }));
  assert.equal(unreported.rows[0].freshness.status, "not_reported");
  assert.equal(unreported.run.freshness.status, "not_reported");

  const expired = adaptRanking(packetWith([rankedRow("a", { freshnessExpiry: "2026-09-01T00:00:00Z" })]));
  assert.equal(expired.rows[0].freshness.status, "stale");

  const generated = adaptRanking(packetWith([rankedRow("a")], { fingerprint: { generatedAt: "2026-09-29T11:00:00Z", freshnessLabel: "age_30d" } }));
  assert.equal(generated.run.freshness.status, "fresh", "a reported generatedAt wins over a static label");
  assert.equal(generated.qualifiers.includes("stale"), false);

  const labelOnly = adaptRanking(packetWith([rankedRow("a")], { fingerprint: { generatedAt: null, freshnessLabel: "age_3d" } }));
  assert.ok(labelOnly.qualifiers.includes("stale"));
});

test("ranking: gaps, gates, conflicts and provenance are carried through as reported", () => {
  const model = adaptRanking(
    packetWith([
      rankedRow("a", {
        missingEvidence: ["supplier_lead_time", "supplier_lead_time", " "],
        hardGates: ["credential_missing"],
        conflicts: ["price_mismatch"],
        assumptions: ["margin_assumed"],
        evidenceReferences: ["ref-1"],
        replayIdentity: "replay-abc",
      }),
    ]),
  );
  const [row] = model.rows;
  assert.deepEqual(row.gaps, ["supplier_lead_time"]);
  assert.deepEqual(row.hardGates, ["credential_missing"]);
  assert.deepEqual(row.conflicts, ["price_mismatch"]);
  assert.deepEqual(row.assumptions, ["margin_assumed"]);
  assert.equal(row.partial, true);
  assert.deepEqual(row.provenance.evidenceReferences, ["ref-1"]);
  assert.equal(row.provenance.replayIdentity, "replay-abc");
});

test("ranking: portfolio membership is only asserted once the portfolio is known", () => {
  const rows = adaptRanking(packetWith([rankedRow("a"), rankedRow("b")])).rows;
  assert.deepEqual(markPortfolioMembership(rows, null).map((row) => row.inPortfolio), [null, null]);
  assert.deepEqual(markPortfolioMembership(rows, ["b"]).map((row) => row.inPortfolio), [false, true]);
  assert.deepEqual(markPortfolioMembership(rows, []).map((row) => row.inPortfolio), [false, false]);
});

// ------------------------------------------------------------ fetch adapter

function response(status, body, { text } = {}) {
  return {
    status,
    ok: status >= 200 && status < 300,
    text: async () => text ?? JSON.stringify(body),
  };
}

function recordingFetch(handler) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init });
    return handler(url, init);
  };
  return { calls, fetchImpl };
}

test("api: builds a GET url from the sole API-base authority and encodes the workspace id", () => {
  assert.equal(buildPortfolioUrl("ws-1"), "/api/owner-research/portfolio?workspace_id=ws-1");
  assert.equal(
    buildPortfolioUrl("a b&c=d", { baseUrl: "https://api.example.com" }),
    "https://api.example.com/api/owner-research/portfolio?workspace_id=a%20b%26c%3Dd",
  );
});

test("api: makes exactly one GET with no body and returns the parsed payload", async () => {
  const payload = portfolioPayload();
  const { calls, fetchImpl } = recordingFetch(() => response(200, payload));
  const controller = new AbortController();
  const result = await fetchOwnerPortfolioPayload({ workspaceId: "ws-1", fetchImpl, signal: controller.signal });
  assert.deepEqual(result, { kind: "ok", payload });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].init.method, "GET");
  assert.equal(calls[0].init.body, undefined);
  assert.equal(calls[0].init.signal, controller.signal);
  assert.deepEqual(calls[0].init.headers, { Accept: "application/json" });
});

test("api: no workspace means no request at all", async () => {
  const { calls, fetchImpl } = recordingFetch(() => response(200, {}));
  for (const workspaceId of [null, "", "   "]) {
    assert.deepEqual(await fetchOwnerPortfolioPayload({ workspaceId, fetchImpl }), { kind: "unavailable", reason: "workspace_not_selected" });
  }
  assert.equal(calls.length, 0);
});

test("api: an absent route is unavailable, real failures are errors, and neither is an empty portfolio", async () => {
  const expectations = [
    [404, { kind: "unavailable", reason: "endpoint_not_available" }],
    [405, { kind: "unavailable", reason: "endpoint_not_available" }],
    [501, { kind: "unavailable", reason: "endpoint_not_available" }],
    [401, { kind: "error", reason: "http_401" }],
    [403, { kind: "error", reason: "http_403" }],
    [500, { kind: "error", reason: "http_500" }],
    [503, { kind: "error", reason: "http_503" }],
  ];
  for (const [status, expected] of expectations) {
    const { fetchImpl } = recordingFetch(() => response(status, {}));
    assert.deepEqual(await fetchOwnerPortfolioPayload({ workspaceId: "ws-1", fetchImpl }), expected, String(status));
  }
});

test("api: network failure, abort, bad json and oversized bodies are typed errors", async () => {
  const networkDown = recordingFetch(() => {
    throw new TypeError("Failed to fetch");
  });
  assert.deepEqual(await fetchOwnerPortfolioPayload({ workspaceId: "ws-1", fetchImpl: networkDown.fetchImpl }), { kind: "error", reason: "network_error" });

  const aborted = recordingFetch(() => {
    const error = new Error("aborted");
    error.name = "AbortError";
    throw error;
  });
  assert.deepEqual(await fetchOwnerPortfolioPayload({ workspaceId: "ws-1", fetchImpl: aborted.fetchImpl }), { kind: "error", reason: "request_aborted" });

  const badJson = recordingFetch(() => response(200, null, { text: "{not json" }));
  assert.deepEqual(await fetchOwnerPortfolioPayload({ workspaceId: "ws-1", fetchImpl: badJson.fetchImpl }), { kind: "error", reason: "malformed_json" });

  const big = recordingFetch(() => response(200, null, { text: "x".repeat(MAX_PORTFOLIO_RESPONSE_CHARS + 1) }));
  assert.deepEqual(await fetchOwnerPortfolioPayload({ workspaceId: "ws-1", fetchImpl: big.fetchImpl }), { kind: "error", reason: "payload_too_large" });
});

test("api: fetch + adapter end to end - a 404 never renders as 0/3 and a valid payload counts distinct ids", async () => {
  const absent = recordingFetch(() => response(404, {}));
  const absentResult = await fetchOwnerPortfolioPayload({ workspaceId: "ws-1", fetchImpl: absent.fetchImpl });
  assert.equal(absentResult.kind, "unavailable");
  assert.equal(portfolioUnavailable(absentResult.reason, "ws-1").activeCount, null);

  const ok = recordingFetch(() =>
    response(200, portfolioPayload({ items: [{ candidate_id: "a", status: "active", quantity: 8 }, { candidate_id: "a", status: "active" }, { candidate_id: "b", status: "active" }] })),
  );
  const okResult = await fetchOwnerPortfolioPayload({ workspaceId: "ws-1", fetchImpl: ok.fetchImpl });
  assert.equal(okResult.kind, "ok");
  assert.equal(adaptPortfolio(okResult.payload).activeCount, 2);
});


// ============================================================================
// Review follow-ups: gaps where a plausible bug would have passed the suite.
// ============================================================================

// ------------------------------------------- hook mapping (pure, tenant-scoped)

test("hook mapping: the workspace REQUESTED is authoritative, never the one the payload claims", () => {
  const foreign = resultToPortfolioModel({ kind: "ok", payload: portfolioPayload({ workspace_id: "ws-evil" }) }, { workspaceId: "ws-1", nowMs: NOW });
  assert.equal(foreign.phase, "error");
  assert.deepEqual(foreign.reasons, ["workspace_mismatch"]);
  assert.equal(foreign.activeCount, null, "a foreign tenant's portfolio is never counted");

  const own = resultToPortfolioModel({ kind: "ok", payload: portfolioPayload() }, { workspaceId: "ws-1", nowMs: NOW });
  assert.equal(own.phase, "ready");
  assert.equal(own.workspaceId, "ws-1");
});

test("hook mapping: every outcome maps to its own phase and none of them reads as an empty portfolio", () => {
  const ctx = { workspaceId: "ws-1", nowMs: NOW };
  const loading = resultToPortfolioModel(null, ctx);
  const unavailable = resultToPortfolioModel({ kind: "unavailable", reason: "endpoint_not_available" }, ctx);
  const failed = resultToPortfolioModel({ kind: "error", reason: "http_500" }, ctx);
  assert.deepEqual([loading.phase, unavailable.phase, failed.phase], ["loading", "unavailable", "error"]);
  assert.deepEqual(unavailable.reasons, ["endpoint_not_available"]);
  assert.deepEqual(failed.reasons, ["http_500"]);
  for (const model of [loading, unavailable, failed]) {
    assert.equal(model.activeCount, null, `${model.phase} must not read as zero`);
    assert.equal(model.workspaceId, "ws-1");
    assert.notEqual(model.phase, "empty");
  }
});

test("hook mapping: no selected workspace wins over any outcome, including a successful payload", () => {
  for (const workspaceId of [null, "", "   "]) {
    for (const result of [null, { kind: "ok", payload: portfolioPayload() }, { kind: "error", reason: "http_500" }]) {
      const model = resultToPortfolioModel(result, { workspaceId, nowMs: NOW });
      assert.equal(model.phase, "unavailable");
      assert.deepEqual(model.reasons, ["workspace_not_selected"]);
      assert.equal(model.activeCount, null);
    }
  }
});

test("hook mapping: freshness advances with the clock for the SAME fetched payload", () => {
  const result = { kind: "ok", payload: portfolioPayload({ generated_at: "2026-09-29T11:00:00Z", expires_at: undefined }) };
  const early = resultToPortfolioModel(result, { workspaceId: "ws-1", nowMs: Date.parse("2026-09-29T12:00:00Z") });
  const later = resultToPortfolioModel(result, { workspaceId: "ws-1", nowMs: Date.parse("2026-09-30T13:00:00Z") });
  assert.equal(early.freshness.status, "fresh");
  assert.equal(later.freshness.status, "stale");
  assert.ok(later.qualifiers.includes("stale"));
  assert.equal(evaluateDraftResearchGate(early, { handlerConnected: true }).enabled, true);
  assert.equal(evaluateDraftResearchGate(later, { handlerConnected: true }).enabled, false, "a portfolio that ages out stops enabling actions");
});

// ------------------------------------------ tenant + mutation-authority variants

test("tenant: workspace ids are compared exactly - case and whitespace variants are foreign tenants", () => {
  for (const claimed of ["WS-1", "Ws-1", " ws-1", "ws-1 ", "ws-1\n", "ws_1", "ws-10", "ws-"]) {
    const model = adaptPortfolio(portfolioPayload({ workspace_id: claimed }));
    assert.equal(model.phase, "error", JSON.stringify(claimed));
    assert.deepEqual(model.reasons, ["workspace_mismatch"], JSON.stringify(claimed));
  }
  for (const claimed of [undefined, null, 7, {}, [], "   "]) {
    const model = adaptPortfolio(portfolioPayload({ workspace_id: claimed }));
    assert.equal(model.phase, "error", JSON.stringify(claimed));
    assert.deepEqual(model.reasons, ["workspace_id_missing"], JSON.stringify(claimed));
  }
});

test("mutation authority: only a literal read_only:true with mutated:false is accepted", () => {
  for (const overrides of [
    { mutated: undefined },
    { mutated: null },
    { mutated: "false" },
    { mutated: 0 },
    { mutated: true },
    { read_only: undefined },
    { read_only: null },
    { read_only: "true" },
    { read_only: 1 },
    { read_only: false },
  ]) {
    const model = adaptPortfolio(portfolioPayload(overrides));
    assert.equal(model.phase, "error", JSON.stringify(overrides));
    assert.deepEqual(model.reasons, ["mutation_authority_rejected"], JSON.stringify(overrides));
  }
  assert.equal(adaptPortfolio(portfolioPayload({ read_only: true, mutated: false })).phase, "ready");
});

// ------------------------------------------------ gate: pinned fail-open/closed

test("gate: unverifiable or degraded portfolios fail closed", () => {
  const invalidFreshness = evaluateDraftResearchGate(adaptPortfolio(portfolioPayload({ generated_at: "not-a-date" })), { handlerConnected: true });
  assert.equal(invalidFreshness.enabled, false);
  assert.ok(invalidFreshness.reasons.some((reason) => /freshness could not be verified/.test(reason)));

  const partial = adaptPortfolio(
    portfolioPayload({ items: [...portfolioPayload().items, { candidate_id: "  padded  ", status: "active" }] }),
  );
  assert.equal(partial.activeCount, 3, "three valid ids");
  assert.ok(partial.qualifiers.includes("partial"));
  const partialGate = evaluateDraftResearchGate(partial, { handlerConnected: true });
  assert.equal(partialGate.enabled, false, "3 valid + 1 malformed entry is not trusted for drafting");
  assert.ok(partialGate.reasons.some((reason) => /ignored as invalid/.test(reason)));
});

test("gate: the documented pass-through cases stay enabled (unreported freshness, manual evidence)", () => {
  const unreported = adaptPortfolio(portfolioPayload({ generated_at: undefined, expires_at: undefined }));
  assert.equal(unreported.freshness.status, "not_reported");
  assert.equal(evaluateDraftResearchGate(unreported, { handlerConnected: true }).enabled, true);

  const manual = adaptPortfolio(portfolioPayload({ evidence_mode: "manual_import" }));
  assert.equal(manual.evidenceMode, "manual");
  assert.equal(evaluateDraftResearchGate(manual, { handlerConnected: true }).enabled, true, "operator-curated evidence may be drafted from");
});

test("gate: every reason is reported, not only the first", () => {
  const model = adaptPortfolio(
    portfolioPayload({ evidence_mode: "fixture_only", expires_at: "2026-09-01T00:00:00Z", draft_research: { eligible: false, reasons: ["gate_open"] } }),
  );
  const gate = evaluateDraftResearchGate(model, { handlerConnected: false });
  assert.equal(gate.enabled, false);
  for (const pattern of [/Fixture \/ simulation/, /stale/, /not eligible/, /gate_open/, /No draft-research service is connected/]) {
    assert.ok(gate.reasons.some((reason) => pattern.test(reason)), `${pattern} in ${JSON.stringify(gate.reasons)}`);
  }
});

// ------------------------------------------------- secret scan: fails closed

test("secret scan: every credential-shaped key pattern is rejected, at any nesting the scan covers", () => {
  const keys = ["client_secret", "access_token", "password", "passwd", "apiKey", "api-key", "api_key", "Authorization", "credentials", "private_key", "private-key", "session_cookie"];
  for (const key of keys) {
    const nested = adaptPortfolio(portfolioPayload({ items: [{ candidate_id: "a", status: "active", meta: { deep: { [key]: "x" } } }] }));
    assert.deepEqual(nested.reasons, ["secret_shaped_field_rejected"], key);
    const arrayed = adaptPortfolio(portfolioPayload({ extras: [[{ [key]: "x" }]] }));
    assert.deepEqual(arrayed.reasons, ["secret_shaped_field_rejected"], `${key} in arrays`);
  }
  assert.equal(scanForSecretKeys({ candidate_id: "a", status: "active", sku: "S", supplier_offer_count: 3 }), "clean");
  assert.equal(scanForSecretKeys({ reasons: ["credential_missing"] }), "clean", "values are not keys");
});

test("secret scan: a payload too deep or too large to scan is rejected, never waved through", () => {
  let deep = { api_key: "x" };
  for (let level = 0; level < 12; level += 1) deep = { wrap: deep };
  assert.equal(scanForSecretKeys(deep), "too_complex");
  const deepModel = adaptPortfolio(portfolioPayload({ extras: deep }));
  assert.deepEqual(deepModel.reasons, ["payload_too_complex"]);

  const wide = adaptPortfolio(portfolioPayload({ items: [{ candidate_id: "a", status: "active", blob: new Array(25_000).fill(1) }] }));
  assert.deepEqual(wide.reasons, ["payload_too_complex"]);
  assert.equal(wide.activeCount, null);
});

// -------------------------------------------------------------- limits

test("limits: exactly 500 portfolio items are accepted, 501 are rejected", () => {
  const at = (count) => Array.from({ length: count }, (_, index) => ({ candidate_id: `c-${index}`, status: "active" }));
  const ok = adaptPortfolio(portfolioPayload({ items: at(500), draft_research: { eligible: true } }));
  assert.equal(ok.phase, "ready");
  assert.equal(ok.activeCount, 500);
  assert.deepEqual(adaptPortfolio(portfolioPayload({ items: at(501) })).reasons, ["items_exceed_limit"]);
});

test("limits: ranked rows beyond the cap are dropped and flagged, not silently cut", () => {
  assert.equal(contracts.MAX_RANKED_ROWS, 200);
  const rows = Array.from({ length: 201 }, (_, index) => rankedRow(`cand-${index}`, { rankIndex: index }));
  const model = adaptRanking(packetWith(rows));
  assert.equal(model.rows.length, 200);
  assert.deepEqual(model.dropped, [{ reason: "rows_truncated", candidateId: null, count: 1 }]);
  assert.ok(model.warnings.includes("rows_truncated:1"));
  assert.ok(model.qualifiers.includes("partial"));
});

test("limits: a truncation entry counts every row past the cap", () => {
  const rows = Array.from({ length: 205 }, (_, index) => rankedRow(`cand-${index}`, { rankIndex: index }));
  const model = adaptRanking(packetWith(rows));
  assert.equal(model.rows.length, 200);
  assert.deepEqual(model.dropped, [{ reason: "rows_truncated", candidateId: null, count: 5 }]);
  assert.ok(model.warnings.includes("rows_truncated:5"));
  assert.equal(stateCopy.describeHiddenRows(model.dropped).total, 5);
});

test("describeHiddenRows: sums counts per reason and never invents a zero", () => {
  const { describeHiddenRows } = stateCopy;
  assert.deepEqual(describeHiddenRows([]), { total: 0, text: "" });
  assert.deepEqual(
    describeHiddenRows([
      { reason: "duplicate_candidate_id", candidateId: "a", count: 1 },
      { reason: "invalid_candidate_id", candidateId: null, count: 1 },
      { reason: "duplicate_candidate_id", candidateId: "b", count: 1 },
      { reason: "rows_truncated", candidateId: null, count: 7 },
    ]),
    { total: 10, text: "2 duplicate candidate IDs, 1 malformed candidate ID, 7 past the 200-row limit" },
  );
});

// ---------------------------------------------- "never re-sorts", for real

test("ranking: order is preserved even when every metric the adapter reads is anti-sorted", () => {
  const anti = (id, index, overrides) => {
    const cells = rankedRow(id).pillarCells.map((cell) => ({ ...cell, score: overrides.pillar }));
    return rankedRow(id, { rankIndex: index, evidenceCompleteness: overrides.completeness, confidence: overrides.confidence, pillarCells: cells });
  };
  const rows = [
    anti("first-but-weakest", 0, { completeness: 0.1, confidence: 0.1, pillar: 0.1 }),
    anti("second-but-strongest", 1, { completeness: 0.9, confidence: 0.9, pillar: 0.9 }),
    anti("third-mid", 2, { completeness: 0.5, confidence: 0.5, pillar: 0.5 }),
  ];
  const model = adaptRanking(packetWith(rows));
  assert.deepEqual(model.rows.map((row) => row.candidateId), ["first-but-weakest", "second-but-strongest", "third-mid"]);
  assert.deepEqual(model.rows.map((row) => row.rankNumber), [1, 2, 3]);
  assert.deepEqual(model.rows.map((row) => row.evidenceCompleteness), [0.1, 0.9, 0.5], "values are carried through, not used to reorder");
  // Joining a portfolio that holds only the LAST-ranked id must not float it to the top.
  const joined = markPortfolioMembership(model.rows, ["third-mid"]);
  assert.deepEqual(joined.map((row) => row.candidateId), ["first-but-weakest", "second-but-strongest", "third-mid"]);
  assert.deepEqual(joined.map((row) => row.inPortfolio), [false, false, true]);
});

// -------------------------------------------- API origin authority (apiBase.ts)

test("api origin: the URL comes from apiBase's VITE_API_BASE_URL, then VITE_API_URL, else same-origin", async () => {
  const seen = [];
  const stub = async (url) => {
    seen.push(url);
    return { status: 200, ok: true, text: async () => JSON.stringify(portfolioPayload()) };
  };
  try {
    globalThis.__IMPORT_META__ = { env: { VITE_API_BASE_URL: "https://api.example.test/", VITE_API_URL: "https://legacy.example.test" } };
    assert.equal(buildPortfolioUrl("ws-1"), "https://api.example.test/api/owner-research/portfolio?workspace_id=ws-1");
    await fetchOwnerPortfolioPayload({ workspaceId: "ws-1", fetchImpl: stub });
    assert.equal(seen.at(-1), "https://api.example.test/api/owner-research/portfolio?workspace_id=ws-1", "the fetch itself uses the authority");

    globalThis.__IMPORT_META__ = { env: { VITE_API_URL: "https://legacy.example.test/" } };
    assert.equal(buildPortfolioUrl("ws-1"), "https://legacy.example.test/api/owner-research/portfolio?workspace_id=ws-1");

    globalThis.__IMPORT_META__ = { env: {} };
    assert.equal(buildPortfolioUrl("ws-1"), "/api/owner-research/portfolio?workspace_id=ws-1");
  } finally {
    delete globalThis.__IMPORT_META__;
  }
  assert.equal(buildPortfolioUrl("ws-1"), "/api/owner-research/portfolio?workspace_id=ws-1", "no env at all stays same-origin");
});

// ------------------------------------------------------ listbox key handling

test("listbox keys: arrows, Home and End move; boundaries consume the key without wrapping", () => {
  const key = (name, extra = {}) => ({ key: name, ...extra });
  assert.deepEqual(resolveListboxKey(key("ArrowDown"), 0, 3), { handled: true, kind: "move", nextIndex: 1 });
  assert.deepEqual(resolveListboxKey(key("ArrowUp"), 2, 3), { handled: true, kind: "move", nextIndex: 1 });
  assert.deepEqual(resolveListboxKey(key("End"), 0, 3), { handled: true, kind: "move", nextIndex: 2 });
  assert.deepEqual(resolveListboxKey(key("Home"), 2, 3), { handled: true, kind: "move", nextIndex: 0 });
  assert.deepEqual(resolveListboxKey(key("ArrowDown"), 2, 3), { handled: true, kind: "none" }, "no wrap at the end");
  assert.deepEqual(resolveListboxKey(key("ArrowUp"), 0, 3), { handled: true, kind: "none" }, "no wrap at the start");
  assert.deepEqual(resolveListboxKey(key("Home"), 0, 3), { handled: true, kind: "none" });
  assert.deepEqual(resolveListboxKey(key("ArrowDown"), 0, 1), { handled: true, kind: "none" }, "single option");
});

test("listbox keys: Enter and Space hand focus to details; nothing else is consumed", () => {
  assert.deepEqual(resolveListboxKey({ key: "Enter" }, 1, 3), { handled: true, kind: "activate" });
  assert.deepEqual(resolveListboxKey({ key: " " }, 1, 3), { handled: true, kind: "activate" });
  for (const name of ["Tab", "Escape", "a", "PageDown", "ArrowLeft", "ArrowRight", "Shift", "F5"]) {
    assert.deepEqual(resolveListboxKey({ key: name }, 1, 3), { handled: false }, name);
  }
  assert.deepEqual(resolveListboxKey({ key: "ArrowDown" }, 0, 0), { handled: false }, "empty list");
});

test("listbox keys: Ctrl, Cmd and Alt combinations are left to the browser", () => {
  for (const key of ["Home", "End", "ArrowUp", "ArrowDown", "Enter", " "]) {
    for (const modifier of ["ctrlKey", "metaKey", "altKey"]) {
      assert.deepEqual(resolveListboxKey({ key, [modifier]: true }, 1, 3), { handled: false }, `${modifier}+${key}`);
    }
  }
  assert.equal(resolveListboxKey({ key: "ArrowDown", shiftKey: true }, 0, 3).handled, true, "Shift alone does not disable navigation");
});

// -------------------------------------------------------- live-region summary

test("live region: announces state changes and never announces an unknown portfolio as zero", () => {
  const LIVE = { fingerprint: { evidenceMode: "live_readonly" } };
  const ready = announceSurface(adaptRanking(packetWith([rankedRow("a"), rankedRow("b", { rankIndex: 1 })], LIVE)), adaptPortfolio(portfolioPayload()));
  assert.equal(ready, "Ranking ready: 2 candidates in backend order. Portfolio: 3 of 3 distinct active candidates.");

  const one = announceSurface(adaptRanking(packetWith([rankedRow("a")], LIVE)), adaptPortfolio(portfolioPayload({ items: [] })));
  assert.match(one, /^Ranking ready: 1 candidate in backend order\. Portfolio: 0 of 3 distinct active candidates\.$/, "a real empty portfolio is zero");

  const loading = adaptRankingPacket({ packet: null, loading: true, loadError: null, nowMs: NOW });
  for (const unknown of [portfolioLoading("ws-1"), portfolioUnavailable("endpoint_not_available", "ws-1"), portfolioError("http_500", "ws-1")]) {
    const text = announceSurface(loading, unknown);
    assert.doesNotMatch(text, /\b0 of 3\b/, `${unknown.phase}: ${text}`);
    assert.match(text, /^Ranking is loading\. Portfolio (is loading|is unavailable|failed to load)\./);
  }
  assert.match(announceSurface(adaptRanking(packetWith([rankedRow("a")], { fingerprint: { evidenceMode: "fixture_only" } })), adaptPortfolio(portfolioPayload())), /Notices: fixture\.$/);
});
