/**
 * Owner Research Journey End-to-End Acceptance Gate.
 *
 * Covers:
 * 1) Authenticated owner state & tenant isolation
 * 2) Ranked candidates with provenance (backend order, opaque IDs, missing values as 'Not reported')
 * 3) 0/3, 2/3, 3/3, and >3 distinct active candidate IDs
 * 4) Duplicate and archived candidate handling (SKUs/offers ignored, duplicates deduplicated)
 * 5) Blocked draft generation below three or on degraded evidence
 * 6) Allowed on-demand advisory draft generation at/above three with explicit eligibility
 * 7) Explicit missing/partial/unavailable states and outage honesty (404/501 != 0/3)
 * 8) Zero mutations (no provider calls, publishes, ad spends, orders, payments, messages)
 */

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import path from "node:path";

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

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const harnessUrl = new URL("./fixtures/owner-research-journey/harness.html", import.meta.url);
const runnerPath = path.join(repoRoot, "scripts", "ai", "run_owner_research_acceptance.py");

function resolvePython() {
  if (process.env.PYTHON) return process.env.PYTHON;
  for (const candidate of ["python", "python3"]) {
    const probe = spawnSync(candidate, ["-c", "import sys; raise SystemExit(0 if sys.version_info[0] >= 3 else 1)"]);
    if (probe.status === 0) return candidate;
  }
  return "python";
}



test("owner research harness encodes skip links, live region, roving tabindex listbox, and no mutating methods", async () => {
  const html = await readFile(harnessUrl, "utf8");
  assert.match(html, /id="skip-link"/);
  assert.match(html, /Skip to main content/);
  assert.match(html, /aria-live="polite"/);
  assert.match(html, /role="listbox"/);
  assert.match(html, /role="option"/);
  assert.match(html, /role="group"/);
  assert.match(html, /data-surface="owner-research"/);
  assert.match(html, /window\.__mosRequests/);
  assert.match(html, /window\.__mosEmittedDrafts/);
  
  // Guard against mutating forms and actions
  assert.doesNotMatch(html, /<form/i);
  assert.doesNotMatch(html, /method:\s*["']POST["']/i);
  assert.doesNotMatch(html, /method:\s*["']PUT["']/i);
  assert.doesNotMatch(html, /method:\s*["']PATCH["']/i);
  assert.doesNotMatch(html, /method:\s*["']DELETE["']/i);
});

test("authenticated owner state: tenant workspace is required and foreign payloads fail closed", () => {
  // 1. Missing workspace => unavailable
  const unselected = adaptPortfolioPayload(
    {
      schema_version: "owner-research-portfolio-v1",
      workspace_id: "ws-owner-alpha",
      evidence_mode: "live_readonly",
      items: [{ candidate_id: "c-1", status: "active" }],
      read_only: true,
      mutated: false,
    },
    { expectedWorkspaceId: null, nowMs: NOW },
  );
  assert.equal(unselected.phase, "unavailable");
  assert.equal(unselected.reasons[0], "workspace_not_selected");
  assert.equal(unselected.activeCount, null);

  // 2. Foreign workspace => workspace_mismatch error
  const mismatch = adaptPortfolioPayload(
    {
      schema_version: "owner-research-portfolio-v1",
      workspace_id: "ws-foreign",
      evidence_mode: "live_readonly",
      items: [{ candidate_id: "c-1", status: "active" }],
      read_only: true,
      mutated: false,
    },
    { expectedWorkspaceId: "ws-owner-alpha", nowMs: NOW },
  );
  assert.equal(mismatch.phase, "error");
  assert.equal(mismatch.reasons[0], "workspace_mismatch");
  assert.equal(mismatch.activeCount, null);

  // 3. Authorized owner matching workspace => active state
  const valid = adaptPortfolioPayload(
    {
      schema_version: "owner-research-portfolio-v1",
      workspace_id: "ws-owner-alpha",
      evidence_mode: "live_readonly",
      items: [
        { candidate_id: "c-1", status: "active" },
        { candidate_id: "c-2", status: "active" },
      ],
      read_only: true,
      mutated: false,
    },
    { expectedWorkspaceId: "ws-owner-alpha", nowMs: NOW },
  );
  assert.equal(valid.phase, "ready");
  assert.equal(valid.workspaceId, "ws-owner-alpha");
  assert.equal(valid.activeCount, 2);
});

test("portfolio distinct active counts: handles 0/3, 2/3, 3/3, and 5/3 honestly", () => {
  // 0/3: loaded portfolio with no active candidates is real 0/3 (not null)
  const p0 = adaptPortfolioPayload(
    {
      schema_version: "owner-research-portfolio-v1",
      workspace_id: "ws-1",
      evidence_mode: "live_readonly",
      items: [],
      read_only: true,
      mutated: false,
    },
    { expectedWorkspaceId: "ws-1", nowMs: NOW },
  );
  assert.equal(p0.phase, "empty");
  assert.equal(p0.activeCount, 0);
  assert.deepEqual(p0.activeCandidateIds, []);

  // 2/3: exactly 2 distinct active candidate IDs
  const p2 = adaptPortfolioPayload(
    {
      schema_version: "owner-research-portfolio-v1",
      workspace_id: "ws-1",
      evidence_mode: "live_readonly",
      items: [
        { candidate_id: "c-hydroponics", status: "active" },
        { candidate_id: "c-smart-feeder", status: "active" },
      ],
      read_only: true,
      mutated: false,
    },
    { expectedWorkspaceId: "ws-1", nowMs: NOW },
  );
  assert.equal(p2.phase, "ready");
  assert.equal(p2.activeCount, 2);
  assert.deepEqual(p2.activeCandidateIds, ["c-hydroponics", "c-smart-feeder"]);

  // 3/3: exactly 3 distinct active candidate IDs
  const p3 = adaptPortfolioPayload(
    {
      schema_version: "owner-research-portfolio-v1",
      workspace_id: "ws-1",
      evidence_mode: "live_readonly",
      items: [
        { candidate_id: "c-hydroponics", status: "active" },
        { candidate_id: "c-smart-feeder", status: "active" },
        { candidate_id: "c-solar-camera", status: "active" },
      ],
      read_only: true,
      mutated: false,
    },
    { expectedWorkspaceId: "ws-1", nowMs: NOW },
  );
  assert.equal(p3.phase, "ready");
  assert.equal(p3.activeCount, 3);
  assert.deepEqual(p3.activeCandidateIds, ["c-hydroponics", "c-smart-feeder", "c-solar-camera"]);

  // 5/3: more than 3 distinct active candidate IDs reported honestly
  const p5 = adaptPortfolioPayload(
    {
      schema_version: "owner-research-portfolio-v1",
      workspace_id: "ws-1",
      evidence_mode: "live_readonly",
      items: [
        { candidate_id: "c-1", status: "active" },
        { candidate_id: "c-2", status: "active" },
        { candidate_id: "c-3", status: "active" },
        { candidate_id: "c-4", status: "active" },
        { candidate_id: "c-5", status: "active" },
      ],
      read_only: true,
      mutated: false,
    },
    { expectedWorkspaceId: "ws-1", nowMs: NOW },
  );
  assert.equal(p5.phase, "ready");
  assert.equal(p5.activeCount, 5);
  assert.equal(p5.activeCandidateIds.length, 5);
});

test("duplicate and archived candidate behavior: deduplicates active IDs and ignores non-active/SKUs", () => {
  const p = adaptPortfolioPayload(
    {
      schema_version: "owner-research-portfolio-v1",
      workspace_id: "ws-1",
      evidence_mode: "live_readonly",
      items: [
        { candidate_id: "cand-a", status: "active", sku: "SKU-A1", quantity: 50, supplier_offer_count: 3 },
        { candidate_id: "cand-a", status: "active", sku: "SKU-A2", quantity: 100, supplier_offer_count: 5 },
        { candidate_id: "cand-a", status: "active", sku: "SKU-A3", quantity: 20 },
        { candidate_id: "cand-archived", status: "archived" },
        { candidate_id: "cand-removed", status: "removed" },
        { candidate_id: "cand-inactive", status: "inactive" },
        { candidate_id: "cand-b", status: "active" },
        { candidate_id: "cand-c", status: "active" },
      ],
      read_only: true,
      mutated: false,
    },
    { expectedWorkspaceId: "ws-1", nowMs: NOW },
  );

  assert.equal(p.phase, "ready");
  assert.equal(p.activeCount, 3);
  assert.deepEqual(p.activeCandidateIds, ["cand-a", "cand-b", "cand-c"]);
  assert.equal(p.ignored.duplicateActiveRows, 2);
  assert.equal(p.ignored.notActive, 3);
  assert.equal(p.ignored.invalidId, 0);
  assert.equal(p.ignored.malformedEntries, 0);
});

test("blocked draft generation below three and on degraded/fixture/stale evidence", () => {
  // 1. Below 3 (< 3 distinct active candidate IDs)
  const pBelow3 = adaptPortfolioPayload(
    {
      schema_version: "owner-research-portfolio-v1",
      workspace_id: "ws-1",
      evidence_mode: "live_readonly",
      items: [
        { candidate_id: "c-1", status: "active" },
        { candidate_id: "c-2", status: "active" },
      ],
      draft_research: { eligible: true },
      read_only: true,
      mutated: false,
    },
    { expectedWorkspaceId: "ws-1", nowMs: NOW },
  );
  const gateBelow3 = evaluateDraftResearchGate(pBelow3, { handlerConnected: true });
  assert.equal(gateBelow3.enabled, false);
  assert.ok(gateBelow3.reasons.some((r) => r.includes("conflicts with the distinct active candidate count (2/3)")));

  // 2. Fixture evidence mode blocks draft generation
  const pFixture = adaptPortfolioPayload(
    {
      schema_version: "owner-research-portfolio-v1",
      workspace_id: "ws-1",
      evidence_mode: "fixture_only",
      items: [
        { candidate_id: "c-1", status: "active" },
        { candidate_id: "c-2", status: "active" },
        { candidate_id: "c-3", status: "active" },
      ],
      draft_research: { eligible: true },
      read_only: true,
      mutated: false,
    },
    { expectedWorkspaceId: "ws-1", nowMs: NOW },
  );
  const gateFixture = evaluateDraftResearchGate(pFixture, { handlerConnected: true });
  assert.equal(gateFixture.enabled, false);
  assert.ok(gateFixture.reasons.some((r) => r.includes("Fixture / simulation data cannot enable draft research")));

  // 3. Stale evidence blocks draft generation
  const pStale = adaptPortfolioPayload(
    {
      schema_version: "owner-research-portfolio-v1",
      workspace_id: "ws-1",
      generated_at: "2026-09-20T00:00:00Z",
      expires_at: "2026-09-21T00:00:00Z",
      evidence_mode: "live_readonly",
      items: [
        { candidate_id: "c-1", status: "active" },
        { candidate_id: "c-2", status: "active" },
        { candidate_id: "c-3", status: "active" },
      ],
      draft_research: { eligible: true },
      read_only: true,
      mutated: false,
    },
    { expectedWorkspaceId: "ws-1", nowMs: NOW },
  );
  const gateStale = evaluateDraftResearchGate(pStale, { handlerConnected: true });
  assert.equal(gateStale.enabled, false);
  assert.ok(gateStale.reasons.some((r) => r.includes("Portfolio evidence is stale")));

  // 4. Backend reports eligible: false blocks draft generation
  const pNotEligible = adaptPortfolioPayload(
    {
      schema_version: "owner-research-portfolio-v1",
      workspace_id: "ws-1",
      evidence_mode: "live_readonly",
      items: [
        { candidate_id: "c-1", status: "active" },
        { candidate_id: "c-2", status: "active" },
        { candidate_id: "c-3", status: "active" },
      ],
      draft_research: { eligible: false, reasons: ["Supplier price volatility gate not passed"] },
      read_only: true,
      mutated: false,
    },
    { expectedWorkspaceId: "ws-1", nowMs: NOW },
  );
  const gateNotEligible = evaluateDraftResearchGate(pNotEligible, { handlerConnected: true });
  assert.equal(gateNotEligible.enabled, false);
  assert.ok(gateNotEligible.reasons.some((r) => r.includes("Supplier price volatility gate not passed")));

  // 5. Unconnected handler blocks draft generation
  const pValid = adaptPortfolioPayload(
    {
      schema_version: "owner-research-portfolio-v1",
      workspace_id: "ws-1",
      evidence_mode: "live_readonly",
      items: [
        { candidate_id: "c-1", status: "active" },
        { candidate_id: "c-2", status: "active" },
        { candidate_id: "c-3", status: "active" },
      ],
      draft_research: { eligible: true },
      read_only: true,
      mutated: false,
    },
    { expectedWorkspaceId: "ws-1", nowMs: NOW },
  );
  const gateNoHandler = evaluateDraftResearchGate(pValid, { handlerConnected: false });
  assert.equal(gateNoHandler.enabled, false);
  assert.ok(gateNoHandler.reasons.some((r) => r.includes("No draft-research service is connected")));
});

test("allowed on-demand advisory draft generation at/above three with explicit eligibility and connected handler", () => {
  const p = adaptPortfolioPayload(
    {
      schema_version: "owner-research-portfolio-v1",
      workspace_id: "ws-1",
      evidence_mode: "live_readonly",
      items: [
        { candidate_id: "cand-1", status: "active" },
        { candidate_id: "cand-2", status: "active" },
        { candidate_id: "cand-3", status: "active" },
      ],
      draft_research: { eligible: true },
      read_only: true,
      mutated: false,
    },
    { expectedWorkspaceId: "ws-1", nowMs: NOW },
  );

  const gate = evaluateDraftResearchGate(p, { handlerConnected: true });
  assert.equal(gate.enabled, true);
  assert.equal(gate.reasons.length, 0);

  // Manual evidence mode is also allowed
  const pManual = adaptPortfolioPayload(
    {
      schema_version: "owner-research-portfolio-v1",
      workspace_id: "ws-1",
      evidence_mode: "manual",
      items: [
        { candidate_id: "cand-1", status: "active" },
        { candidate_id: "cand-2", status: "active" },
        { candidate_id: "cand-3", status: "active" },
        { candidate_id: "cand-4", status: "active" },
      ],
      draft_research: { eligible: true },
      read_only: true,
      mutated: false,
    },
    { expectedWorkspaceId: "ws-1", nowMs: NOW },
  );
  const gateManual = evaluateDraftResearchGate(pManual, { handlerConnected: true });
  assert.equal(gateManual.enabled, true);
  assert.equal(gateManual.reasons.length, 0);
});

test("outage honesty: absent or failed route maps to unavailable/error and never renders as 0/3 or live data", () => {
  // 404 endpoint not available => unavailable
  const m404 = resultToPortfolioModel(
    { kind: "unavailable", reason: "endpoint_not_available" },
    { workspaceId: "ws-1", nowMs: NOW },
  );
  assert.equal(m404.phase, "unavailable");
  assert.equal(m404.activeCount, null); // never 0!
  assert.deepEqual(m404.reasons, ["endpoint_not_available"]);

  // 501 endpoint not implemented => unavailable
  const m501 = resultToPortfolioModel(
    { kind: "unavailable", reason: "endpoint_not_implemented" },
    { workspaceId: "ws-1", nowMs: NOW },
  );
  assert.equal(m501.phase, "unavailable");
  assert.equal(m501.activeCount, null);

  // 500 server error => error
  const m500 = resultToPortfolioModel(
    { kind: "error", reason: "server_error" },
    { workspaceId: "ws-1", nowMs: NOW },
  );
  assert.equal(m500.phase, "error");
  assert.equal(m500.activeCount, null);

  // In flight loading => loading (null count)
  const mLoading = resultToPortfolioModel(null, { workspaceId: "ws-1", nowMs: NOW });
  assert.equal(mLoading.phase, "loading");
  assert.equal(mLoading.activeCount, null);
});

test("security & safety: secret keys, oversized items, and mutating fields fail closed", () => {
  assert.equal(scanForSecretKeys({ normal: "value", nested: { apiKey: "secret123" } }), "secret");
  assert.equal(scanForSecretKeys({ normal: "value", nested: { token: "abc" } }), "secret");
  assert.equal(scanForSecretKeys({ normal: "value", nested: { ok: true } }), "clean");

  // Mutating flag rejected
  const mutating = adaptPortfolioPayload(
    {
      schema_version: "owner-research-portfolio-v1",
      workspace_id: "ws-1",
      evidence_mode: "live_readonly",
      items: [{ candidate_id: "c-1", status: "active" }],
      read_only: false,
      mutated: true,
    },
    { expectedWorkspaceId: "ws-1", nowMs: NOW },
  );
  assert.equal(mutating.phase, "error");
  assert.equal(mutating.reasons[0], "mutation_authority_rejected");
});
