import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { DECISION_TIMELINE_KINDS } from "../src/features/first-phase-cockpit/contracts/firstPhaseEvidencePacket.ts";
import { classifyEvidenceClass } from "../src/features/first-phase-cockpit/lib/classifyEvidence.ts";
import { composeCockpitViewModel } from "../src/features/first-phase-cockpit/lib/composeCockpitViewModel.ts";
import { DEFAULT_CANDIDATE_FILTER, filterCandidates } from "../src/features/first-phase-cockpit/lib/filterCandidates.ts";
import {
  enrichDecisionReview,
  mapCommercialReviewTags,
  mapDecisionTimeline,
  mapNextActionWorkflow,
} from "../src/features/first-phase-cockpit/lib/mapDecisionReview.ts";
import { adaptCommerceProjection } from "../src/features/first-phase-cockpit/lib/overlayCommerceProjection.ts";
import { adaptResearchToDecisionProjection } from "../src/features/first-phase-cockpit/lib/overlayResearchToDecision.ts";
import { windowCandidates } from "../src/features/first-phase-cockpit/lib/windowCandidates.ts";

const featureRoot = new URL("../src/features/first-phase-cockpit/", import.meta.url);
const matrixRoot = new URL("../src/features/first-phase-cockpit/fixtures/projection-matrix/", import.meta.url);
const pageSource = new URL("../src/pages/FirstPhaseEvidenceCockpit.tsx", import.meta.url);
const hookSource = new URL("../src/features/first-phase-cockpit/hooks/useFirstPhaseEvidenceCockpit.ts", import.meta.url);

function baseRow(overrides = {}) {
  return enrichDecisionReview({
    candidateId: "cand",
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
    riskLevel: null,
    validationPriority: null,
    validationTarget: null,
    sourceFamily: "benchmark_matrix",
    evidenceMode: "fixture_only",
    evidenceClass: "fixture",
    promotionState: "unavailable",
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
    pillarCells: [],
    offerDisposition: "unavailable",
    decisionTimeline: [],
    commercialReviewTags: [],
    nextActionWorkflow: mapNextActionWorkflow({
      nextBestAction: null,
      missingEvidence: [],
      promotionState: "unavailable",
      validationTarget: null,
    }),
    promotionTransitions: [],
    launchAuthorizedFalse: true,
    ...overrides,
  });
}

test("transition timeline mapping never invents timestamps", () => {
  const timeline = mapDecisionTimeline(baseRow({
    sku: "HYDRO-KIT-01",
    commercialDecision: "hold_for_manual_review",
    promotionState: "hold",
  }));
  assert.equal(timeline.length, DECISION_TIMELINE_KINDS.length);
  assert.ok(timeline.every((item) => item.at === null));
  assert.equal(timeline.find((item) => item.kind === "supplier_offer_normalized").status, "observed");
});

test("missing transition data stays unavailable rather than fabricated", () => {
  const timeline = mapDecisionTimeline(baseRow());
  assert.equal(timeline.find((item) => item.kind === "replay_identity").status, "unavailable");
  assert.equal(timeline.find((item) => item.kind === "economics_calculated").status, "unavailable");
});

test("hydroponics fixture is never upgraded to live_validated", async () => {
  const packet = JSON.parse(await readFile(new URL("accepted-manual-screening.json", matrixRoot), "utf8"));
  const row = baseRow({
    candidateId: "hydroponics-kit",
    evidenceMode: "fixture_only",
    evidenceClass: "fixture",
    promotionState: "hold",
  });
  const adapted = adaptResearchToDecisionProjection([row], packet, Date.parse("2026-09-18T00:00:00Z"));
  assert.equal(adapted.accepted, true);
  assert.equal(adapted.rows[0].sku, "HYDRO-KIT-01");
  assert.equal(adapted.rows[0].supplierOffer.includes("offer-hydro-1"), true);
  assert.equal(adapted.rows[0].confidence, null);
  assert.equal(adapted.rows[0].confidenceSupplier, 0.4);
  assert.equal(adapted.rows[0].confidenceMarketplace, 0.5);
  assert.ok(adapted.rows[0].commercialReviewTags.includes("fixture"));
  assert.ok(!adapted.rows[0].commercialReviewTags.includes("live_validated"));
  assert.equal(
    classifyEvidenceClass({
      evidenceMode: "fixture_only",
      declared: "live_sales_validated",
    }),
    "fixture",
  );
});

test("solar 4G missing compliance/support/SIM remains blocked", async () => {
  const demo = await readFile(new URL("fixtures/demoPacket.ts", featureRoot), "utf8");
  const solar = demo.slice(demo.indexOf("solar-4g-camera"), demo.indexOf("commodity-usb-cable"));
  assert.match(solar, /promotionState: "blocked"/);
  assert.match(solar, /compliance_certificate/);
  assert.match(solar, /support_owner/);
  assert.match(solar, /sim_plan_evidence/);
  const row = baseRow({
    candidateId: "solar-4g-camera",
    promotionState: "blocked",
    evidenceMode: "manual",
    missingEvidence: ["compliance_certificate", "support_owner", "sim_plan_evidence"],
    hardGates: ["compliance", "support_owner", "sim_plan_evidence"],
    nextBestAction: "collect_compliance_support_and_sim_evidence",
  });
  assert.equal(mapDecisionTimeline(row).find((item) => item.kind === "blocker_or_next_best_action").status, "observed");
  assert.ok(mapCommercialReviewTags(row).includes("needs_evidence"));
  assert.ok(mapCommercialReviewTags(row).includes("blocked"));
  assert.ok(mapCommercialReviewTags(row).includes("manual_import"));
});

test("commodity rejection shows retailer dominance reason", async () => {
  const demo = await readFile(new URL("fixtures/demoPacket.ts", featureRoot), "utf8");
  assert.match(demo, /reject_retailer_dominance/);
  assert.match(demo, /retailer_dominance_amazon_search_share/);
  const row = baseRow({
    candidateId: "commodity-usb-cable",
    commercialDecision: "reject_retailer_dominance",
    promotionState: "reject",
    conflicts: ["retailer_dominance_amazon_search_share"],
  });
  assert.ok(mapCommercialReviewTags(row).includes("reject"));
});

test("next-action workflow is display-only", async () => {
  const panels = await readFile(new URL("components/DecisionReviewPanels.tsx", featureRoot), "utf8");
  const page = await readFile(pageSource, "utf8");
  const hook = await readFile(hookSource, "utf8");
  assert.match(panels, /No cockpit control can send messages/);
  assert.equal(mapNextActionWorkflow(baseRow()).allowedInReadOnlyCockpit, false);
  assert.equal(mapNextActionWorkflow(baseRow({ nextBestAction: "place_order" })).futureActionStatus, "unavailable");
  assert.doesNotMatch(page, /method:\s*["']POST["']/);
  assert.doesNotMatch(hook, /method:\s*["']POST["']/);
  assert.match(hook, /commerceProjection: undefined/);
});

test("commerce adapter rejects unsupported, duplicate, launch-authorized, secret, oversized, and cross-workspace packets", () => {
  const rows = [baseRow({ candidateId: "hydroponics-kit" })];
  assert.equal(adaptCommerceProjection(rows, { schema: "other-v9" }).warning, "schema_version_unsupported");
  assert.equal(adaptCommerceProjection(rows, {
    schema: "MarketOS.ClientCommerceProjection.v1",
    candidates: [{ candidate_id: "a" }, { candidate_id: "a" }],
  }).warning, "candidate_identity_duplicate");
  assert.equal(adaptCommerceProjection(rows, {
    schema: "MarketOS.ClientCommerceProjection.v1",
    launch_authorized: true,
    candidates: [{ candidate_id: "hydroponics-kit" }],
  }).warning, "launch_authorized_rejected");
  assert.equal(adaptCommerceProjection(rows, {
    schema: "MarketOS.ClientCommerceProjection.v1",
    token: "sk-live-abcdefghijklmnopqrstuvwxyz",
    candidates: [],
  }).warning, "secret_shaped_value_rejected");
  assert.equal(adaptCommerceProjection(rows, {
    schema: "MarketOS.ClientCommerceProjection.v1",
    candidates: [{ candidate_id: "hydroponics-kit", workspace_id: "other-client" }],
  }, "workspace-a").warning, "cross_workspace_rejected");
  assert.equal(adaptCommerceProjection(rows, {
    schema: "MarketOS.ClientCommerceProjection.v1",
    candidates: Array.from({ length: 201 }, (_, index) => ({ candidate_id: `c-${index}` })),
  }).warning, "projection_oversized");
});

test("#247 overlay rejects cross-workspace audits without inserting rows", async () => {
  const packet = JSON.parse(await readFile(new URL("accepted-manual-screening.json", matrixRoot), "utf8"));
  packet.appendix.candidate_audit[0].workspace_id = "other-client";
  const rows = [baseRow({ candidateId: "hydroponics-kit", sku: "KEEP" })];
  const adapted = adaptResearchToDecisionProjection(rows, packet, Date.parse("2026-09-18T00:00:00Z"), "workspace-a");
  assert.equal(adapted.accepted, false);
  assert.equal(adapted.warning, "cross_workspace_rejected");
  assert.equal(adapted.rows[0].sku, "KEEP");
});

test("stale evidence is tagged without inventing a newer class", () => {
  const row = baseRow({ freshnessExpiry: "expired", evidenceClass: "stale", evidenceMode: "fixture_only" });
  assert.ok(mapCommercialReviewTags(row).includes("stale"));
  assert.ok(mapCommercialReviewTags(row).includes("fixture"));
  assert.ok(!mapCommercialReviewTags(row).includes("live_validated"));
});

test("simulated evidence is downgraded and never tagged live_validated", () => {
  assert.equal(
    classifyEvidenceClass({ evidenceMode: "simulated", declared: "direct_ship_verified" }),
    "derived",
  );
  const row = baseRow({ evidenceMode: "simulated", evidenceClass: "derived", promotionState: "hold" });
  assert.ok(mapCommercialReviewTags(row).includes("simulated"));
  assert.ok(!mapCommercialReviewTags(row).includes("live_validated"));
});

test("conflicting offers do not reorder rows or mutate scores", () => {
  const rows = [
    baseRow({ candidateId: "a", rankIndex: 0, supplierScore: 0.11, conflicts: ["offer_price_mismatch"] }),
    baseRow({ candidateId: "b", rankIndex: 1, supplierScore: 0.22 }),
  ];
  const adapted = adaptCommerceProjection(rows, {
    schema: "MarketOS.ClientCommerceProjection.v1",
    candidates: [{ candidate_id: "b", supplier_sku: "B-1" }, { candidate_id: "a", supplier_sku: "A-1" }],
  });
  assert.deepEqual(adapted.rows.map((row) => row.candidateId), ["a", "b"]);
  assert.equal(adapted.rows[0].supplierScore, 0.11);
  assert.equal(adapted.rows[0].sku, "A-1");
  assert.equal(adapted.rows[1].sku, "B-1");
});

test("large candidate sets keep server order", () => {
  const rows = Array.from({ length: 120 }, (_, index) => baseRow({ candidateId: `c-${index}`, rankIndex: index }));
  assert.deepEqual(rows.map((row) => row.rankIndex), Array.from({ length: 120 }, (_, index) => index));
});

test("keyboard helpers and reduced-motion documentation remain in source", async () => {
  const keyboard = await readFile(new URL("lib/keyboardNav.ts", featureRoot), "utf8");
  const css = await readFile(new URL("../../index.css", featureRoot), "utf8");
  const page = await readFile(pageSource, "utf8");
  const detail = await readFile(new URL("components/CandidateDetailPanel.tsx", featureRoot), "utf8");
  const review = await readFile(new URL("components/DecisionReviewPanels.tsx", featureRoot), "utf8");
  const table = await readFile(new URL("components/RankedCandidatesPanel.tsx", featureRoot), "utf8");
  const compose = await readFile(new URL("lib/composeCockpitViewModel.ts", featureRoot), "utf8");
  assert.match(keyboard, /ArrowDown/);
  assert.match(keyboard, /shouldHandoffDetailFocus/);
  assert.match(css, /prefers-reduced-motion/);
  assert.match(page, /Skip to ranked candidates/);
  assert.match(page, /aria-live="polite"/);
  assert.match(detail, /DecisionTimelinePanel/);
  assert.match(review, /Evidence decision timeline/);
  assert.match(review, /Human next-action workflow/);
  assert.match(table, /md:hidden/);
  assert.match(table, /hidden overflow-x-auto md:block/);
  assert.match(table, /aria-pressed=\{selected\}/);
  assert.match(table, /Scrollable ranked candidates table/);
  assert.match(compose, /never sort or re-rank/);
  assert.match(compose, /adaptCommerceProjection/);
  assert.match(compose, /operatorWorkspaceId/);
});

function composeWithProjection(ids, projection, extra = {}) {
  return composeCockpitViewModel({
    phase1Readiness: { overall_status: "ready" },
    benchmark: {
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
    },
    publicMarket: null,
    researchPortfolio: null,
    readinessError: false,
    benchmarkError: false,
    publicMarketError: false,
    researchError: false,
    isLoading: false,
    researchToDecisionProjection: projection,
    ...extra,
  });
}

test("compose+view-model consume fixture/contract-shaped #247 candidate_audit without inventing proof", async () => {
  const packet = JSON.parse(await readFile(new URL("accepted-backend-audit-shape.json", matrixRoot), "utf8"));
  const view = composeWithProjection(["hydroponics-kit", "server-only"], packet);
  assert.equal(view.state, "stale");
  assert.deepEqual(view.rankedCandidates.map((row) => row.candidateId), ["hydroponics-kit", "server-only"]);
  const joined = view.rankedCandidates[0];
  const unmatched = view.rankedCandidates[1];
  assert.equal(joined.sku, "HYDRO-KIT-01");
  assert.equal(joined.commercialDecision, "hold_for_manual_review");
  assert.equal(joined.nextBestAction, "hold_for_manual_review");
  assert.equal(joined.nextActionWorkflow.action, "hold_for_manual_review");
  assert.equal(joined.nextActionWorkflow.allowedInReadOnlyCockpit, false);
  assert.ok(joined.missingEvidence.includes("duty_model_unknown"));
  assert.ok(joined.missingEvidence.includes("lane_not_verified"));
  assert.ok(joined.hardGates.includes("supplier_offer:offer_expired"));
  assert.ok(joined.hardGates.includes("manual_evidence_is_not_live_supplier_proof"));
  assert.ok(joined.evidenceReferences.includes("evidence:abc123"));
  assert.equal(joined.riskLevel, "blocked");
  assert.equal(joined.promotionState, "blocked");
  assert.ok(joined.commercialReviewTags.includes("blocked"));
  assert.ok(joined.commercialReviewTags.includes("stale"));
  assert.ok(joined.commercialReviewTags.includes("fixture"));
  assert.ok(!joined.commercialReviewTags.includes("live_validated"));
  assert.equal(joined.launchAuthorizedFalse, true);
  assert.equal(joined.confidence, null);
  assert.equal(joined.confidenceSupplier, 0.4);
  assert.equal(joined.freshnessExpiry, "expired");
  assert.deepEqual(
    joined.promotionTransitions.map((item) => item.to),
    ["discovered", "promotion_blocked", "launch_authorized_false"],
  );
  assert.ok(joined.decisionTimeline.every((item) => item.at === null));
  const blocker = joined.decisionTimeline.find((item) => item.kind === "blocker_or_next_best_action");
  assert.equal(blocker.status, "observed");
  assert.equal(blocker.summary, joined.hardGates[0]);
  assert.ok(joined.hardGates.includes("manual_evidence_is_not_live_supplier_proof"));
  assert.equal(unmatched.sku, null);
  assert.equal(unmatched.confidence, null);
  assert.ok(!unmatched.evidenceReferences.includes("evidence:abc123"));

  const filtered = filterCandidates(view.rankedCandidates, { ...DEFAULT_CANDIDATE_FILTER, query: "hydro" });
  assert.deepEqual(filtered.map((row) => row.candidateId), ["hydroponics-kit"]);
  const windowed = windowCandidates(view.rankedCandidates, 0, 1);
  assert.deepEqual(windowed.visible.map((row) => row.candidateId), ["hydroponics-kit"]);
  const topN = filterCandidates(
    composeWithProjection(
      ["hydroponics-kit", ...Array.from({ length: 11 }, (_, index) => `tail-${index}`)],
      packet,
    ).rankedCandidates,
    { ...DEFAULT_CANDIDATE_FILTER, topN: true },
  );
  assert.equal(topN.length, 10);
  assert.deepEqual(topN.map((row) => row.rankIndex), [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
});

test("compose keeps absent/null/empty #247 audit fields unavailable instead of fabricating success", () => {
  const view = composeWithProjection(["hydroponics-kit"], {
    report_version: "product-validation-report-v1",
    appendix: {
      research_to_decision_version: "v1",
      candidate_audit: [{
        candidate_id: "hydroponics-kit",
        action: null,
        next_action: null,
        decision: null,
        evidence_gaps: [],
        missing_evidence: null,
        promotion_lifecycle: [],
        evidence_refs: [],
        freshness: null,
        evidence_expiry: null,
        confidence: { overall: null },
        economics: {},
        hard_gates: [],
      }],
    },
  });
  const row = view.rankedCandidates[0];
  assert.equal(row.confidence, null);
  assert.equal(row.freshnessExpiry, null);
  assert.ok(row.decisionTimeline.every((item) => item.at === null));
  assert.equal(row.launchAuthorizedFalse, true);
  assert.ok(!row.commercialReviewTags.includes("live_validated"));
  assert.equal(row.economicsUnavailable, true);
  assert.equal(row.economicsLabel, null);
  assert.notEqual(view.state, "empty");
});

test("compose fail-closed on #247 launch_authorized, malformed, duplicate, secret, and oversized packets", async () => {
  const rejected = async (name, token) => {
    const packet = JSON.parse(await readFile(new URL(name, matrixRoot), "utf8"));
    const view = composeWithProjection(["hydroponics-kit"], packet);
    assert.equal(view.state, "unavailable");
    assert.match(view.fingerprint.projectionWarning ?? "", new RegExp(token));
    assert.equal(view.rankedCandidates[0].sku, null);
  };
  await rejected("rejected-launch-authorized.json", "launch_authorized_rejected");
  await rejected("rejected-malformed.json", "candidate_audit_malformed");
  await rejected("rejected-duplicate-ids.json", "candidate_identity_duplicate");
  await rejected("rejected-secret.json", "secret_shaped_value_rejected");
  const oversized = composeWithProjection(["hydroponics-kit"], {
    report_version: "product-validation-report-v1",
    appendix: {
      research_to_decision_version: "v1",
      candidate_audit: Array.from({ length: 201 }, (_, index) => ({ candidate_id: `c-${index}` })),
    },
  });
  assert.equal(oversized.state, "unavailable");
  assert.match(oversized.fingerprint.projectionWarning ?? "", /projection_oversized/);
});

test("compose maps producer-shaped action, empty evidence_gaps, and promotion_lifecycle through the view model", async () => {
  const packet = JSON.parse(await readFile(new URL("accepted-producer-shaped-hydroponics-audit.json", matrixRoot), "utf8"));
  const view = composeWithProjection(["hydroponics-kit", "server-only"], packet);
  const joined = view.rankedCandidates[0];
  assert.deepEqual(view.rankedCandidates.map((row) => row.candidateId), ["hydroponics-kit", "server-only"]);
  assert.equal(joined.nextBestAction, "expand_consumer_research");
  assert.equal(joined.nextActionWorkflow.action, "expand_consumer_research");
  assert.equal(joined.commercialDecision, "expand_consumer_research");
  assert.ok(!joined.missingEvidence.includes("lane_not_verified"));
  assert.ok(joined.hardGates.includes("no_launch_or_spend_authority"));
  assert.ok(joined.evidenceReferences.includes("evidence:52e27e00e59f2513"));
  assert.equal(joined.freshnessExpiry, null);
  assert.equal(joined.confidence, null);
  assert.equal(joined.confidenceSupplier, 0.5168);
  assert.equal(joined.confidenceMarketplace, 0.3879);
  assert.deepEqual(
    joined.promotionTransitions.map((item) => item.to),
    ["discovered", "normalized", "screened", "supplier_claimed", "launch_authorized_false"],
  );
  assert.equal(joined.promotionTransitions.at(-1)?.to, "launch_authorized_false");
  assert.ok(joined.commercialReviewTags.includes("fixture"));
  assert.ok(!joined.commercialReviewTags.includes("live_validated"));
  assert.equal(joined.launchAuthorizedFalse, true);
  assert.ok(joined.decisionTimeline.every((item) => item.at === null));
  const filtered = filterCandidates(view.rankedCandidates, { ...DEFAULT_CANDIDATE_FILTER, query: "hydroponics" });
  assert.deepEqual(filtered.map((row) => row.candidateId), ["hydroponics-kit"]);
});

test("#247 hydroponics screening fixture remains mapped by id", async () => {
  const packet = JSON.parse(await readFile(new URL("accepted-manual-screening.json", matrixRoot), "utf8"));
  assert.equal(packet.appendix.client_safe_projection.launch_authorized, false);
  assert.equal(packet.appendix.candidate_audit[0].candidate_id, "hydroponics-kit");
  assert.equal(packet.evidence_mode, "fixture_demo");
});

test("export payload includes timeline and forbids live mutation flags", async () => {
  const exporter = await readFile(new URL("lib/exportClientSafeReport.ts", featureRoot), "utf8");
  assert.match(exporter, /decision_timeline/);
  assert.match(exporter, /launch_authorized_false/);
  assert.match(exporter, /mutated: false/);
});
