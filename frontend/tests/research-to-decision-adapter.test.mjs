import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { composeCockpitViewModel } from "../src/features/first-phase-cockpit/lib/composeCockpitViewModel.ts";
import { enrichDecisionReview } from "../src/features/first-phase-cockpit/lib/mapDecisionReview.ts";
import {
  adaptResearchToDecisionProjection,
  validateResearchToDecisionProjection,
} from "../src/features/first-phase-cockpit/lib/overlayResearchToDecision.ts";

const matrixRoot = new URL("../src/features/first-phase-cockpit/fixtures/projection-matrix/", import.meta.url);
const featureRoot = new URL("../src/features/first-phase-cockpit/", import.meta.url);
const NOW = Date.parse("2026-09-18T00:00:00Z");

function serverRow(overrides = {}) {
  return enrichDecisionReview({
    candidateId: "hydroponics-kit",
    title: "Candidate",
    productTitle: "Candidate",
    sku: null,
    rankIndex: 0,
    evidenceCompleteness: null,
    supplierScore: null,
    competitionScore: null,
    economicsLabel: null,
    assumptionRatio: null,
    commercialDecision: null,
    nextBestAction: null,
    riskLevel: "medium",
    validationPriority: null,
    validationTarget: null,
    sourceFamily: "benchmark_matrix",
    evidenceMode: "fixture_only",
    evidenceClass: "fixture",
    promotionState: "hold",
    marketLane: null,
    supplierOffer: null,
    confidence: null,
    confidenceSupplier: null,
    confidenceMarketplace: null,
    assumptions: [],
    missingEvidence: [],
    conflicts: [],
    hardGates: [],
    evidenceReferences: [],
    consumerAttentionSummary: null,
    competitionSummary: null,
    replayIdentity: null,
    freshnessExpiry: null,
    supplierEvidenceClass: "fixture",
    consumerEvidenceClass: "not_run",
    economicsUnavailable: true,
    isTopCandidate: false,
    pillarCells: [
      { pillarId: "freshness", label: "Freshness", score: null, status: "partial", detail: null, evidenceClass: "derived" },
    ],
    offerDisposition: "unavailable",
    decisionTimeline: [],
    commercialReviewTags: [],
    nextActionWorkflow: {
      action: "unavailable",
      missingEvidence: [],
      responsibleParty: "unavailable",
      expectedEvidenceType: "unavailable",
      humanConfirmationRequired: false,
      allowedInReadOnlyCockpit: false,
      futureActionStatus: "unavailable",
      futureActionNote: "Cockpit cannot mutate external systems.",
    },
    promotionTransitions: [],
    launchAuthorizedFalse: true,
    ...overrides,
  });
}

function emptyCompose(overrides = {}) {
  return composeCockpitViewModel({
    phase1Readiness: null,
    benchmark: null,
    publicMarket: null,
    researchPortfolio: null,
    readinessError: false,
    benchmarkError: false,
    publicMarketError: false,
    researchError: false,
    isLoading: false,
    ...overrides,
  });
}

function benchmarkWith(ids) {
  return {
    top_candidate_id: ids[0] ?? null,
    next_best_action: "review_evidence",
    evidence_mode: "fixture_demo",
    warnings: [],
    read_only: true,
    mutated: false,
    network_calls: false,
    candidates: ids.map((candidate_id) => ({
      candidate: { candidate_id, title: candidate_id },
      evidence_completeness: 0.4,
      risk_level: "medium",
      commercial_decision: "hold_for_manual_review",
      next_best_action: "hold_for_manual_review",
      supplier_evidence: { score: 0.4 },
      competition_evidence: { score: 0.5 },
      economics: { margin_quality: "assumption", assumption_ratio: 0.8 },
      validation_priority: { priority: "high", target: "duty_model" },
    })),
  };
}

async function loadFixture(name) {
  return JSON.parse(await readFile(new URL(name, matrixRoot), "utf8"));
}

test("accepted #247-shaped screening projection maps by candidate_id without averaging confidence", async () => {
  const packet = await loadFixture("accepted-manual-screening.json");
  assert.equal(validateResearchToDecisionProjection(packet).ok, true);
  const rows = [
    serverRow({ candidateId: "hydroponics-kit", rankIndex: 0 }),
    serverRow({ candidateId: "server-only", rankIndex: 1, sku: null, riskLevel: "low" }),
  ];
  const adapted = adaptResearchToDecisionProjection(rows, packet, NOW);
  assert.equal(adapted.accepted, true);
  assert.deepEqual(adapted.rows.map((row) => row.candidateId), ["hydroponics-kit", "server-only"]);
  assert.equal(adapted.rows[0].sku, "HYDRO-KIT-01");
  assert.equal(adapted.rows[0].marketLane?.destination, "Mexico");
  assert.match(adapted.rows[0].supplierOffer ?? "", /offer-hydro-1/);
  assert.equal(adapted.rows[0].confidence, null);
  assert.equal(adapted.rows[0].confidenceSupplier, 0.4);
  assert.equal(adapted.rows[0].confidenceMarketplace, 0.5);
  assert.equal(adapted.rows[0].economicsUnavailable, false);
  assert.match(adapted.rows[0].economicsLabel ?? "", /gross_margin_percent_28/);
  assert.deepEqual(adapted.unmatchedServerIds, ["server-only"]);
  assert.equal(adapted.rows[1].sku, null);
  assert.equal(adapted.rows[0].nextActionWorkflow.allowedInReadOnlyCockpit, false);
});

test("producer input_audit filesystem labels do not reject overlay candidate_audit", async () => {
  const packet = await loadFixture("accepted-producer-shaped-hydroponics-audit.json");
  assert.equal(validateResearchToDecisionProjection(packet).ok, true);
  const adapted = adaptResearchToDecisionProjection(
    [serverRow({ candidateId: "hydroponics-kit" }), serverRow({ candidateId: "server-only", rankIndex: 1 })],
    packet,
    NOW,
  );
  assert.equal(adapted.accepted, true);
  assert.equal(adapted.rows[0].nextBestAction, "expand_consumer_research");
  assert.equal(adapted.rows[0].commercialDecision, "expand_consumer_research");
  assert.deepEqual(adapted.rows.map((row) => row.candidateId), ["hydroponics-kit", "server-only"]);
});

test("projection matrix rejects unsupported, duplicate, secret, malformed, and launch-authorized packets", async () => {
  assert.equal((await validateResearchToDecisionProjection(await loadFixture("rejected-unsupported-version.json"))).reason, "schema_version_unsupported");
  assert.equal((await validateResearchToDecisionProjection(await loadFixture("rejected-duplicate-ids.json"))).reason, "candidate_identity_duplicate");
  assert.equal((await validateResearchToDecisionProjection(await loadFixture("rejected-secret.json"))).reason, "secret_shaped_value_rejected");
  assert.equal((await validateResearchToDecisionProjection(await loadFixture("rejected-malformed.json"))).reason, "candidate_audit_malformed");
  assert.equal((await validateResearchToDecisionProjection(await loadFixture("rejected-launch-authorized.json"))).reason, "launch_authorized_rejected");
  assert.equal(
    validateResearchToDecisionProjection({
      report_version: "product-validation-report-v1",
      appendix: { research_to_decision_version: "v1", candidate_audit: [{ title: "missing-id" }] },
    }).reason,
    "candidate_identity_missing",
  );
});

test("#247 overlay rejects cross-workspace audits when operator workspace is known", async () => {
  const packet = await loadFixture("accepted-manual-screening.json");
  packet.appendix.candidate_audit[0].workspace_id = "other-client";
  const rows = [serverRow({ sku: "KEEP" })];
  const adapted = adaptResearchToDecisionProjection(rows, packet, NOW, "workspace-a");
  assert.equal(adapted.accepted, false);
  assert.equal(adapted.warning, "cross_workspace_rejected");
  assert.equal(adapted.rows[0].sku, "KEEP");
});

test("partial appendix is accepted and extra fields are ignored", async () => {
  const packet = await loadFixture("partial-appendix.json");
  assert.equal(validateResearchToDecisionProjection(packet).ok, true);
  const adapted = adaptResearchToDecisionProjection([serverRow({ candidateId: "alpha", sku: "KEEP" })], packet, NOW);
  assert.equal(adapted.accepted, true);
  assert.equal(adapted.rows[0].sku, "KEEP");
});

test("stale report rows without server matches are not inserted", async () => {
  const packet = await loadFixture("stale-unmatched.json");
  const adapted = adaptResearchToDecisionProjection(
    [serverRow({ candidateId: "hydroponics-kit", sku: null, riskLevel: "medium" })],
    packet,
    NOW,
  );
  assert.equal(adapted.accepted, true);
  assert.equal(adapted.rows.length, 1);
  assert.equal(adapted.rows[0].freshnessExpiry, "expired");
  assert.equal(adapted.rows[0].evidenceClass, "stale");
  assert.ok(adapted.rows[0].commercialReviewTags.includes("stale"));
  assert.ok(adapted.rows[0].commercialReviewTags.includes("fixture"));
  assert.ok(!adapted.rows[0].commercialReviewTags.includes("live_validated"));
  assert.equal(adapted.rows[0].riskLevel, "blocked");
  assert.ok(adapted.rows[0].commercialReviewTags.includes("blocked"));
  assert.equal(adapted.rows[0].economicsUnavailable, true);
  assert.deepEqual(adapted.unmatchedProjectionIds, ["report-only-row"]);
});

test("unavailable confidence is not coerced to zero", () => {
  const packet = {
    report_version: "product-validation-report-v1",
    appendix: {
      research_to_decision_version: "v1",
      candidate_audit: [{
        candidate_id: "hydroponics-kit",
        confidence: { overall: null, supplier: 0 },
      }],
    },
  };
  const adapted = adaptResearchToDecisionProjection([serverRow()], packet, NOW);
  assert.equal(adapted.rows[0].confidence, null);
  assert.equal(adapted.rows[0].confidenceSupplier, 0);
});

test("oversized candidate audits are rejected", () => {
  const packet = {
    report_version: "product-validation-report-v1",
    appendix: {
      research_to_decision_version: "v1",
      candidate_audit: Array.from({ length: 201 }, (_, index) => ({ candidate_id: `c-${index}` })),
    },
  };
  assert.equal(validateResearchToDecisionProjection(packet).reason, "projection_oversized");
});

test("compose surfaces loading empty blocked unavailable stale partial success without ranking", async () => {
  assert.equal(emptyCompose({ isLoading: true }).state, "loading");
  assert.equal(emptyCompose().state, "empty");
  assert.equal(emptyCompose({ readinessError: true, benchmarkError: true }).state, "unavailable");
  assert.equal(emptyCompose({
    phase1Readiness: { overall_status: "blocked" },
  }).state, "blocked");

  const packet = await loadFixture("accepted-manual-screening.json");
  packet.appendix.candidate_audit[0].workspace_id = "other-client";
  const unavailable = composeCockpitViewModel({
    phase1Readiness: { overall_status: "ready" },
    benchmark: benchmarkWith(["hydroponics-kit"]),
    publicMarket: null,
    researchPortfolio: { workspace_id: "workspace-a" },
    readinessError: false,
    benchmarkError: false,
    publicMarketError: false,
    researchError: false,
    isLoading: false,
    researchToDecisionProjection: packet,
    operatorWorkspaceId: "workspace-a",
  });
  assert.equal(unavailable.state, "unavailable");
  assert.match(unavailable.fingerprint.projectionWarning ?? "", /cross_workspace_rejected/);

  const stalePacket = await loadFixture("stale-unmatched.json");
  const stale = composeCockpitViewModel({
    phase1Readiness: { overall_status: "ready" },
    benchmark: benchmarkWith(["hydroponics-kit"]),
    publicMarket: null,
    researchPortfolio: null,
    readinessError: false,
    benchmarkError: false,
    publicMarketError: false,
    researchError: false,
    isLoading: false,
    researchToDecisionProjection: stalePacket,
  });
  assert.equal(stale.state, "stale");
  assert.deepEqual(stale.rankedCandidates.map((row) => row.candidateId), ["hydroponics-kit"]);

  const partial = composeCockpitViewModel({
    phase1Readiness: { overall_status: "partially_ready" },
    benchmark: benchmarkWith(["hydroponics-kit"]),
    publicMarket: null,
    researchPortfolio: null,
    readinessError: false,
    benchmarkError: false,
    publicMarketError: true,
    researchError: false,
    isLoading: false,
  });
  assert.equal(partial.state, "partial");

  const success = composeCockpitViewModel({
    phase1Readiness: { overall_status: "ready" },
    benchmark: benchmarkWith(["hydroponics-kit"]),
    publicMarket: null,
    researchPortfolio: null,
    readinessError: false,
    benchmarkError: false,
    publicMarketError: false,
    researchError: false,
    isLoading: false,
    researchToDecisionProjection: await loadFixture("accepted-manual-screening.json"),
  });
  assert.equal(success.state, "success");
  assert.deepEqual(success.rankedCandidates.map((row) => row.candidateId), ["hydroponics-kit"]);
  assert.equal(success.rankedCandidates[0].sku, "HYDRO-KIT-01");
  assert.ok(success.controlPlanes.some((slot) => slot.id === "trustos" && slot.status === "unavailable"));
  assert.ok(success.controlPlanes.some((slot) => slot.id === "governor" && slot.status === "unavailable"));
  assert.ok(success.controlPlanes.some((slot) => slot.id === "approval_ledger" && slot.status === "unavailable"));
});

test("#247 backend audit shape maps action, evidence_gaps, promotion_lifecycle, blocked, and expired freshness", async () => {
  const packet = await loadFixture("accepted-backend-audit-shape.json");
  const adapted = adaptResearchToDecisionProjection([serverRow()], packet, NOW);
  assert.equal(adapted.accepted, true);
  const row = adapted.rows[0];
  assert.equal(row.sku, "HYDRO-KIT-01");
  assert.equal(row.nextBestAction, "hold_for_manual_review");
  assert.equal(row.promotionState, "blocked");
  assert.ok(row.commercialReviewTags.includes("blocked"));
  assert.ok(row.missingEvidence.includes("duty_model_unknown"));
  assert.ok(row.missingEvidence.includes("lane_not_verified"));
  assert.equal(row.confidence, null);
  assert.equal(row.confidenceSupplier, 0.4);
  assert.equal(row.nextActionWorkflow.allowedInReadOnlyCockpit, false);
  assert.equal(row.freshnessExpiry, "expired");
  assert.ok(row.commercialReviewTags.includes("stale"));
  assert.ok(!row.commercialReviewTags.includes("live_validated"));
  assert.deepEqual(
    row.promotionTransitions.map((item) => item.to),
    ["discovered", "promotion_blocked", "launch_authorized_false"],
  );
  assert.ok(row.decisionTimeline.every((item) => item.at === null));
});

test("adapter source remains identity-preserving and fail-closed", async () => {
  const source = await readFile(new URL("lib/overlayResearchToDecision.ts", featureRoot), "utf8");
  assert.match(source, /adaptResearchToDecisionProjection/);
  assert.match(source, /candidate_identity_duplicate/);
  assert.match(source, /candidate_identity_missing/);
  assert.match(source, /launch_authorized_rejected/);
  assert.match(source, /projection_oversized/);
  assert.match(source, /cross_workspace_rejected/);
  assert.match(source, /optionalNumber/);
  assert.match(source, /Never coerce null to 0|never.*average confidence/i);
  assert.doesNotMatch(source, /\.sort\(/);
  assert.doesNotMatch(source, /\(supplier \+ market\) \/ 2/);
});
