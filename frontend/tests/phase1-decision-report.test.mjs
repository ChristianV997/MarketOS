import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import {
  adaptPhase1DecisionReport,
  classifyEvidenceAuthority,
  isLiveSupplierProof,
  resolveDecisionReportState,
} from "../src/features/first-phase-cockpit/lib/adaptPhase1DecisionReport.ts";

const fixtureUrl = new URL(
  "../src/features/first-phase-cockpit/fixtures/phase1DecisionReport.fixture.json",
  import.meta.url,
);
const pageUrl = new URL("../src/pages/FirstPhaseEvidenceCockpit.tsx", import.meta.url);
const panelUrl = new URL(
  "../src/features/first-phase-cockpit/components/Phase1DecisionReportPanel.tsx",
  import.meta.url,
);

test("classifyEvidenceAuthority distinguishes fixture from live supplier proof", () => {
  assert.equal(classifyEvidenceAuthority("fixture_only"), "fixture_or_manual");
  assert.equal(classifyEvidenceAuthority("live_observed", "supplier"), "live_supplier_proof");
  assert.equal(classifyEvidenceAuthority("live_observed", "competition"), "partial_or_degraded");
  assert.equal(classifyEvidenceAuthority("ready", "safety"), "structural_ready");
  assert.equal(classifyEvidenceAuthority("blocked"), "blocked");
  assert.equal(classifyEvidenceAuthority("partially_ready"), "partial_or_degraded");
  assert.equal(classifyEvidenceAuthority("not_configured"), "unavailable");
  assert.equal(isLiveSupplierProof("live_observed"), true);
  assert.equal(isLiveSupplierProof("fixture_only"), false);
  assert.equal(isLiveSupplierProof("partially_ready"), false);
});

test("resolveDecisionReportState covers loading empty error success", () => {
  assert.equal(resolveDecisionReportState({ isLoading: true, isError: false, data: null }), "loading");
  assert.equal(resolveDecisionReportState({ isLoading: false, isError: true, data: null }), "error");
  assert.equal(resolveDecisionReportState({ isLoading: false, isError: false, data: null }), "empty");
  assert.equal(
    resolveDecisionReportState({ isLoading: false, isError: false, data: { overall_status: "blocked" } }),
    "success",
  );
});

test("adaptPhase1DecisionReport maps stable readiness fixture into operator journey", async () => {
  const fixture = JSON.parse(await readFile(fixtureUrl, "utf8"));
  const report = adaptPhase1DecisionReport({ isLoading: false, isError: false, data: fixture });

  assert.equal(report.state, "success");
  assert.equal(report.overallStatus, "blocked");
  assert.equal(report.overallScore, 38.6);
  assert.equal(report.nextBestAction, "run_offline_public_market_benchmark");
  assert.match(report.nextBestPromptHint ?? "", /offline public-market benchmark/i);
  assert.ok(report.blockingGates.includes("authenticated_supplier_evidence_not_live_observed"));
  assert.equal(report.supplierIsLiveProof, false);
  assert.equal(report.competitionIsLiveObserved, false);
  assert.equal(report.readOnly, true);
  assert.equal(report.mutated, false);
  assert.equal(report.networkCalls, false);
  assert.ok(report.assumptionLabels.some((line) => /planning assumption/i.test(line)));
  assert.ok(report.provenanceLines.some((line) => /supplier/i.test(line)));
  assert.ok(report.categories.length >= 3);

  const supplier = report.categories.find((row) => row.key === "supplier");
  assert.ok(supplier);
  assert.equal(supplier.authority, "fixture_or_manual");
  assert.match(supplier.status, /fixture only/);

  const credentials = report.categories.find((row) => row.key === "credentials");
  assert.ok(credentials);
  assert.equal(credentials.authority, "blocked");
});

test("adaptPhase1DecisionReport does not treat competition live_observed as supplier proof", () => {
  const report = adaptPhase1DecisionReport({
    isLoading: false,
    isError: false,
    data: {
      overall_status: "partially_ready",
      overall_score: 50,
      supplier_readiness: { status: "fixture_only", observed_field_count: 0, coverage: 0 },
      competition_readiness: { status: "live_observed", observed_offer_count: 3, pricing_coverage: 0.5 },
      score_contributions: {
        supplier: { status: "fixture_only", weight: 10, points: 4 },
        competition: { status: "live_observed", weight: 10, points: 10 },
      },
      blocking_gates: ["authenticated_supplier_evidence_not_live_observed"],
      advisory_warnings: [],
      next_best_action: "set_cj_credentials_and_validate_candidate:demo",
      read_only: true,
      mutated: false,
      network_calls: false,
    },
  });
  assert.equal(report.supplierIsLiveProof, false);
  assert.equal(report.competitionIsLiveObserved, true);
  const competition = report.categories.find((row) => row.key === "competition");
  assert.equal(competition?.authority, "partial_or_degraded");
});

test("formats readiness coverage ratios as percentages", () => {
  const report = adaptPhase1DecisionReport({
    isLoading: false,
    isError: false,
    data: {
      supplier_readiness: { status: "fixture_only", observed_field_count: 2, coverage: 0.2 },
      competition_readiness: { status: "live_observed", observed_offer_count: 3, pricing_coverage: 0.5 },
    },
  });
  assert.match(report.categories.find((row) => row.key === "supplier")?.detail ?? "", /coverage 20%/);
  assert.match(report.categories.find((row) => row.key === "competition")?.detail ?? "", /pricing coverage 50%/);
});

test("adaptPhase1DecisionReport error and empty states are explicit", () => {
  const errorView = adaptPhase1DecisionReport({
    isLoading: false,
    isError: true,
    errorMessage: "Unable to load operator events (503).",
    data: null,
  });
  assert.equal(errorView.state, "error");
  assert.match(errorView.errorMessage ?? "", /503|unavailable/i);

  const emptyView = adaptPhase1DecisionReport({ isLoading: false, isError: false, data: null });
  assert.equal(emptyView.state, "empty");
  assert.match(emptyView.emptyMessage ?? "", /GET \/api\/phase1\/readiness/);
});

test("page wires Phase1DecisionReportPanel without touching shared nav or public-market API edits", async () => {
  const page = await readFile(pageUrl, "utf8");
  const panel = await readFile(panelUrl, "utf8");
  const hook = await readFile(new URL("../src/features/first-phase-cockpit/hooks/usePhase1DecisionReport.ts", import.meta.url), "utf8");
  assert.match(page, /Phase1DecisionReportPanel/);
  assert.match(page, /usePhase1DecisionReport/);
  assert.match(page, /phase1-decision-report/);
  assert.match(panel, /GET \/api\/phase1\/readiness/);
  assert.match(hook, /Phase 1 readiness request failed/);
  assert.match(panel, /Not live supplier proof|Live observed/);
  assert.doesNotMatch(panel, /marketplace_trend_report|opportunity_synthesis/);
  assert.doesNotMatch(page, /fetchPublicMarketBenchmark/);
});
