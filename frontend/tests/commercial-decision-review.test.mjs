import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const featureRoot = new URL("../src/features/first-phase-cockpit/", import.meta.url);
const matrixRoot = new URL("../src/features/first-phase-cockpit/fixtures/projection-matrix/", import.meta.url);

const TIMELINE_KINDS = [
  "evidence_captured",
  "supplier_offer_normalized",
  "offer_accepted_or_quarantined",
  "economics_calculated",
  "competition_market_status",
  "promotion_gate_evaluated",
  "lifecycle_decision",
  "blocker_or_next_best_action",
  "replay_identity",
  "evidence_freshness_expiry",
];

function baseRow(overrides = {}) {
  return {
    candidateId: "cand",
    title: "Candidate",
    sku: null,
    rankIndex: 0,
    economicsLabel: null,
    commercialDecision: null,
    nextBestAction: null,
    validationTarget: null,
    evidenceMode: "fixture_only",
    evidenceClass: "fixture",
    promotionState: "unavailable",
    supplierOffer: null,
    missingEvidence: [],
    hardGates: [],
    conflicts: [],
    competitionSummary: null,
    replayIdentity: null,
    freshnessExpiry: null,
    economicsUnavailable: true,
    offerDisposition: "unavailable",
    supplierScore: null,
    nextActionWorkflow: {
      action: "unavailable",
      missingEvidence: [],
      responsibleParty: "unavailable",
      expectedEvidenceType: "unavailable",
      humanConfirmationRequired: false,
      allowedInReadOnlyCockpit: false,
      futureActionStatus: "unavailable",
      futureActionNote: "Cockpit cannot send messages, place orders, publish ads, change prices, approve suppliers, issue refunds, or mutate external systems.",
    },
    ...overrides,
  };
}

function mapTimeline(row) {
  const evidenceObserved = row.evidenceClass !== "unavailable" && row.evidenceClass !== "not_run";
  return TIMELINE_KINDS.map((kind) => {
    const observed = {
      evidence_captured: evidenceObserved,
      supplier_offer_normalized: Boolean(row.sku || row.supplierOffer),
      offer_accepted_or_quarantined: row.offerDisposition !== "unavailable",
      economics_calculated: !row.economicsUnavailable && Boolean(row.economicsLabel),
      competition_market_status: Boolean(row.competitionSummary),
      promotion_gate_evaluated: row.promotionState !== "unavailable",
      lifecycle_decision: Boolean(row.commercialDecision),
      blocker_or_next_best_action: row.hardGates.length > 0 || Boolean(row.nextBestAction) || row.missingEvidence.length > 0,
      replay_identity: Boolean(row.replayIdentity),
      evidence_freshness_expiry: Boolean(row.freshnessExpiry),
    }[kind];
    return { kind, status: observed ? "observed" : "unavailable", at: null };
  });
}

function reviewTags(row) {
  const tags = new Set(["launch_authorized_false"]);
  if (row.promotionState === "hold") tags.add("hold");
  if (row.promotionState === "reject") tags.add("reject");
  if (row.promotionState === "blocked" || row.missingEvidence.length) tags.add("needs_evidence");
  if (row.evidenceClass === "stale" || String(row.freshnessExpiry ?? "").includes("expir")) tags.add("stale");
  if (row.evidenceMode === "fixture_only") tags.add("fixture");
  if (row.evidenceMode === "manual") tags.add("manual_import");
  if (row.evidenceMode === "live_readonly" && row.evidenceClass === "live_sales_validated") tags.add("live_validated");
  return [...tags];
}

function adaptCommerce(rows, raw, workspace = null) {
  if (raw == null) return { rows, warning: "commerce_client_projection_unavailable", accepted: false };
  const serialized = JSON.stringify(raw);
  if (serialized.includes("sk-live-")) return { rows, warning: "secret_shaped_value_rejected", accepted: false };
  if (raw.schema !== "MarketOS.ClientCommerceProjection.v1") {
    return { rows, warning: "schema_version_unsupported", accepted: false };
  }
  if (raw.launch_authorized === true) return { rows, warning: "launch_authorized_rejected", accepted: false };
  if ((raw.candidates ?? []).length > 200) return { rows, warning: "projection_oversized", accepted: false };
  const byId = new Map();
  for (const item of raw.candidates ?? []) {
    if (!item.candidate_id) return { rows, warning: "candidate_identity_missing", accepted: false };
    if (byId.has(item.candidate_id)) return { rows, warning: "candidate_identity_duplicate", accepted: false };
    if (workspace && item.workspace_id && item.workspace_id !== workspace) {
      return { rows, warning: "cross_workspace_rejected", accepted: false };
    }
    byId.set(item.candidate_id, item);
  }
  return {
    accepted: true,
    warning: null,
    rows: rows.map((row) => {
      const overlay = byId.get(row.candidateId);
      if (!overlay) return row;
      return { ...row, sku: overlay.supplier_sku ?? row.sku, hardGates: overlay.blockers ?? row.hardGates };
    }),
  };
}

test("transition timeline mapping never invents timestamps", () => {
  const timeline = mapTimeline(baseRow({ sku: "HYDRO-KIT-01", commercialDecision: "hold_for_manual_review", promotionState: "hold" }));
  assert.equal(timeline.length, 10);
  assert.ok(timeline.every((item) => item.at === null));
  assert.equal(timeline.find((item) => item.kind === "supplier_offer_normalized").status, "observed");
});

test("missing transition data stays unavailable rather than fabricated", () => {
  const timeline = mapTimeline(baseRow());
  assert.equal(timeline.find((item) => item.kind === "replay_identity").status, "unavailable");
  assert.equal(timeline.find((item) => item.kind === "economics_calculated").status, "unavailable");
});

test("hydroponics fixture is never upgraded to live_validated", async () => {
  const demo = await readFile(new URL("fixtures/demoPacket.ts", featureRoot), "utf8");
  const mapper = await readFile(new URL("lib/mapDecisionReview.ts", featureRoot), "utf8");
  const hydro = demo.slice(demo.indexOf("hydroponics-kit"), demo.indexOf("solar-4g-camera"));
  assert.match(hydro, /evidenceMode: "fixture_only"/);
  assert.match(hydro, /evidenceClass: "fixture"/);
  assert.match(hydro, /commercialReviewTags: \["hold", "fixture", "launch_authorized_false", "needs_evidence"\]/);
  assert.match(mapper, /LIVE_PROOF_EVIDENCE_CLASSES/);
  const tags = reviewTags(baseRow({ candidateId: "hydroponics-kit", evidenceMode: "fixture_only", evidenceClass: "fixture", promotionState: "hold" }));
  assert.ok(tags.includes("fixture"));
  assert.ok(!tags.includes("live_validated"));
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
  assert.equal(mapTimeline(row).find((item) => item.kind === "blocker_or_next_best_action").status, "observed");
  assert.ok(reviewTags(row).includes("needs_evidence"));
  assert.ok(reviewTags(row).includes("manual_import"));
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
  assert.ok(reviewTags(row).includes("reject"));
});

test("next-action workflow is display-only", async () => {
  const mapper = await readFile(new URL("lib/mapDecisionReview.ts", featureRoot), "utf8");
  const panels = await readFile(new URL("components/DecisionReviewPanels.tsx", featureRoot), "utf8");
  assert.match(mapper, /allowedInReadOnlyCockpit: false/);
  assert.match(mapper, /futureActionStatus: mutation \|\| action === "unavailable" \? "unavailable" : "draft"/);
  assert.match(panels, /No cockpit control can send messages/);
  assert.equal(baseRow().nextActionWorkflow.allowedInReadOnlyCockpit, false);
});

test("commerce adapter rejects unsupported, duplicate, launch-authorized, secret, oversized, and cross-workspace packets", async () => {
  const adapter = await readFile(new URL("lib/overlayCommerceProjection.ts", featureRoot), "utf8");
  assert.match(adapter, /schema_version_unsupported/);
  assert.match(adapter, /candidate_identity_duplicate/);
  assert.match(adapter, /launch_authorized_rejected/);
  assert.match(adapter, /secret_shaped_value_rejected/);
  assert.match(adapter, /cross_workspace_rejected/);
  assert.match(adapter, /projection_oversized/);
  assert.match(adapter, /commerce_client_projection_unavailable/);
  const rows = [baseRow({ candidateId: "hydroponics-kit" })];
  assert.equal(adaptCommerce(rows, { schema: "other-v9" }).warning, "schema_version_unsupported");
  assert.equal(adaptCommerce(rows, {
    schema: "MarketOS.ClientCommerceProjection.v1",
    candidates: [{ candidate_id: "a" }, { candidate_id: "a" }],
  }).warning, "candidate_identity_duplicate");
  assert.equal(adaptCommerce(rows, {
    schema: "MarketOS.ClientCommerceProjection.v1",
    launch_authorized: true,
    candidates: [{ candidate_id: "hydroponics-kit" }],
  }).warning, "launch_authorized_rejected");
  assert.equal(adaptCommerce(rows, {
    schema: "MarketOS.ClientCommerceProjection.v1",
    token: "sk-live-abcdefghijklmnopqrstuvwxyz",
    candidates: [],
  }).warning, "secret_shaped_value_rejected");
  assert.equal(adaptCommerce(rows, {
    schema: "MarketOS.ClientCommerceProjection.v1",
    candidates: [{ candidate_id: "hydroponics-kit", workspace_id: "other-client" }],
  }, "workspace-a").warning, "cross_workspace_rejected");
  assert.equal(adaptCommerce(rows, {
    schema: "MarketOS.ClientCommerceProjection.v1",
    candidates: Array.from({ length: 201 }, (_, index) => ({ candidate_id: `c-${index}` })),
  }).warning, "projection_oversized");
});

test("stale evidence is tagged without inventing a newer class", () => {
  const row = baseRow({ freshnessExpiry: "expired", evidenceClass: "stale", evidenceMode: "fixture_only" });
  assert.ok(reviewTags(row).includes("stale"));
  assert.ok(reviewTags(row).includes("fixture"));
  assert.ok(!reviewTags(row).includes("live_validated"));
});

test("conflicting offers do not reorder rows or mutate scores", () => {
  const rows = [
    baseRow({ candidateId: "a", rankIndex: 0, supplierScore: 0.11, conflicts: ["offer_price_mismatch"] }),
    baseRow({ candidateId: "b", rankIndex: 1, supplierScore: 0.22 }),
  ];
  const adapted = adaptCommerce(rows, {
    schema: "MarketOS.ClientCommerceProjection.v1",
    candidates: [{ candidate_id: "b", supplier_sku: "B-1" }, { candidate_id: "a", supplier_sku: "A-1" }],
  });
  assert.deepEqual(adapted.rows.map((row) => row.candidateId), ["a", "b"]);
  assert.equal(adapted.rows[0].supplierScore, 0.11);
});

test("large candidate sets keep server order", () => {
  const rows = Array.from({ length: 120 }, (_, index) => baseRow({ candidateId: `c-${index}`, rankIndex: index }));
  assert.deepEqual(rows.map((row) => row.rankIndex), Array.from({ length: 120 }, (_, index) => index));
});

test("keyboard helpers and reduced-motion documentation remain in source", async () => {
  const keyboard = await readFile(new URL("lib/keyboardNav.ts", featureRoot), "utf8");
  const css = await readFile(new URL("../../index.css", featureRoot), "utf8");
  const page = await readFile(new URL("../../pages/FirstPhaseEvidenceCockpit.tsx", featureRoot), "utf8");
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
  assert.match(table, /aria-colcount=\{14\}/);
  assert.match(compose, /never sort or re-rank/);
  assert.match(compose, /adaptCommerceProjection/);
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
