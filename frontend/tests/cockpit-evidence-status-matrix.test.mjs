import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import {
  capSlotStatusForEvidenceMode,
  composeCockpitViewModel,
} from "../src/features/first-phase-cockpit/lib/composeCockpitViewModel.ts";
import { buildClientSafeExport } from "../src/features/first-phase-cockpit/lib/exportClientSafeReport.ts";

function compose(overrides = {}) {
  return composeCockpitViewModel({
    phase1Readiness: { overall_status: "ready" },
    benchmark: {
      evidence_mode: "fixture_demo",
      top_candidate_id: "cand-1",
      candidates: [
        {
          candidate: { candidate_id: "cand-1", title: "Fixture candidate" },
          evidence_completeness: 0.8,
          competition_evidence: { score: 0.9 },
          supplier_evidence: { score: 0.85 },
          economics: { margin_quality: "assumption" },
          commercial_decision: "hold",
          next_best_action: "review_evidence",
          risk_level: "medium",
        },
      ],
      warnings: [],
      read_only: true,
    },
    publicMarket: { competitor_offers_observed: 2, pricing_coverage: 0.5, evidence_mode: "fixture" },
    researchPortfolio: { quality: { research_freshness: 0.71 } },
    readinessError: false,
    benchmarkError: false,
    publicMarketError: false,
    researchError: false,
    isLoading: false,
    ...overrides,
  });
}

test("cross-surface evidence matrix: cockpit slot presence is not fixture live proof", () => {
  const fixture = compose();
  assert.equal(fixture.state, "partial");
  assert.notEqual(fixture.state, "success");
  const market = fixture.pillars.find((pillar) => pillar.id === "market_evidence");
  assert.equal(market.status, "partial");
  assert.equal(market.evidenceClass, "fixture");
  assert.notEqual(market.status, "available");
  for (const pillar of fixture.pillars) {
    if (pillar.evidenceClass === "fixture" || pillar.evidenceClass === "assumption" || pillar.evidenceClass === "derived") {
      assert.notEqual(pillar.status, "available");
    }
  }
  const highScoreCell = fixture.rankedCandidates[0].pillarCells.find((cell) => cell.pillarId === "market_evidence");
  assert.equal(highScoreCell.status, "partial");
  assert.equal(highScoreCell.evidenceClass, "fixture");

  const exported = buildClientSafeExport(fixture, "2026-09-20T00:00:00Z");
  assert.equal(exported.evidence_mode, "fixture_only");
  assert.equal(exported.ranked_candidates[0].launch_authorized_false, true);
  const exportedMarket = exported.pillars.find((pillar) => pillar.pillar_id === "market_evidence");
  assert.equal(exportedMarket.status, "partial");
  assert.equal(exportedMarket.evidence_class, "fixture");
  assert.equal(exportedMarket.launch_authorized, false);

  const unknown = compose({
    benchmark: { evidence_mode: "mystery", top_candidate_id: null, candidates: [], warnings: [], read_only: true },
    publicMarket: null,
  });
  assert.equal(unknown.state, "empty");
  assert.ok(unknown.pillars.every((pillar) => pillar.status !== "available"));

  const missing = compose({
    phase1Readiness: null,
    benchmark: null,
    publicMarket: null,
    researchPortfolio: null,
    readinessError: true,
    benchmarkError: true,
  });
  assert.equal(missing.state, "unavailable");

  const stale = compose({
    phase1Readiness: { overall_status: "degraded" },
  });
  assert.equal(stale.state, "stale");

  const manual = compose({
    benchmark: {
      evidence_mode: "manual_import",
      top_candidate_id: "cand-1",
      candidates: [
        {
          candidate: { candidate_id: "cand-1", title: "Manual candidate" },
          competition_evidence: { score: 0.95 },
          supplier_evidence: { score: 0.2 },
        },
      ],
      warnings: [],
      read_only: true,
    },
    publicMarket: { competitor_offers_observed: 1, pricing_coverage: 0.2, evidence_mode: "manual" },
  });
  assert.equal(manual.state, "partial");
  const manualMarket = manual.pillars.find((pillar) => pillar.id === "market_evidence");
  assert.equal(manualMarket.status, "partial");
  assert.notEqual(manualMarket.evidenceClass, "live_sales_validated");

  assert.equal(capSlotStatusForEvidenceMode("available", "fixture_only"), "partial");
  assert.equal(capSlotStatusForEvidenceMode("available", "live_readonly"), "available");
  assert.equal(capSlotStatusForEvidenceMode("unavailable", "fixture_only"), "unavailable");
});

test("cockpit source never promotes offline modes to available chips", async () => {
  const composeSource = await readFile(new URL("../src/features/first-phase-cockpit/lib/composeCockpitViewModel.ts", import.meta.url), "utf8");
  const panel = await readFile(new URL("../src/features/first-phase-cockpit/components/EvidencePillarsPanel.tsx", import.meta.url), "utf8");
  assert.match(composeSource, /capSlotStatusForEvidenceMode/);
  assert.match(composeSource, /OFFLINE_EVIDENCE_MODES/);
  assert.match(panel, /slot present/);
  assert.match(panel, /not launch authorized/);
  assert.doesNotMatch(composeSource, /method:\s*["']POST["']/);
});
