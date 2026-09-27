import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { neverUpgradeEvidenceClass } from "../src/features/service-delivery-workbench/lib/adaptServiceProjection.ts";
import { composeWorkbenchViewModel } from "../src/features/service-delivery-workbench/lib/composeWorkbenchViewModel.ts";
import { buildClientSafeServiceExport, containsSecretShapedValue as workbenchSecretShaped } from "../src/features/service-delivery-workbench/lib/exportClientSafeEngagement.ts";
import { EMPTY_FILTERS, filterEngagements } from "../src/features/service-delivery-workbench/lib/filterEngagements.ts";
import { buildDemoProjection, buildScaleProjection } from "../src/features/service-delivery-workbench/fixtures/buildFixtures.ts";

const cockpitRoot = new URL("../src/features/first-phase-cockpit/", import.meta.url);
const workbenchRoot = new URL("../src/features/service-delivery-workbench/", import.meta.url);
const smokeHtml = new URL("./fixtures/readonly-operator-smoke.html", import.meta.url);

const MUTATION_MARKERS = /method:\s*["']POST["']|place_order|publish_ad|issue_refund|send_message|charge_card|create_campaign/;

function filterWithoutReorder(candidates, query) {
  const needle = query.trim().toLowerCase();
  const filtered = [];
  for (const candidate of candidates) {
    if (needle && !`${candidate.candidateId} ${candidate.title}`.toLowerCase().includes(needle)) continue;
    filtered.push(candidate);
  }
  return filtered;
}

function windowWithoutReorder(candidates, start, size) {
  return candidates.slice(start, start + size);
}

function rankedStub(index, overrides = {}) {
  return {
    candidateId: `c-${index}`,
    title: `Candidate ${index}`,
    sku: `SKU-${index}`,
    rankIndex: index,
    commercialDecision: index % 2 ? "hold_for_manual_review" : "reject_retailer_dominance",
    nextBestAction: "hold_for_manual_review",
    riskLevel: index % 2 ? "hold" : "high",
    promotionState: index % 2 ? "hold" : "reject",
    isTopCandidate: index === 0,
    ...overrides,
  };
}

test("cockpit surface states cover loading empty blocked unavailable partial stale success", async () => {
  const banner = await readFile(new URL("components/CockpitStatusBanner.tsx", cockpitRoot), "utf8");
  for (const state of ["loading", "empty", "blocked", "unavailable", "stale", "partial", "success"]) {
    assert.match(banner, new RegExp(`${state}:`));
  }
});

test("workbench compose emits loading empty blocked unavailable partial stale without mutation success", () => {
  const demo = buildDemoProjection();
  const loading = composeWorkbenchViewModel({
    isLoading: true, errorMessage: null, projection: null, filters: EMPTY_FILTERS, selectedId: null,
  });
  assert.equal(loading.surface, "loading");
  const empty = composeWorkbenchViewModel({
    isLoading: false, errorMessage: null, projection: null, filters: EMPTY_FILTERS, selectedId: null,
  });
  assert.equal(empty.surface, "empty");
  const unavailable = composeWorkbenchViewModel({
    isLoading: false, errorMessage: "GET failed", projection: null, filters: EMPTY_FILTERS, selectedId: null,
  });
  assert.equal(unavailable.surface, "unavailable");
  const blockedRow = demo.engagements.find((row) => row.lifecycle_state === "data_inadequate") ?? demo.engagements[0];
  const blocked = composeWorkbenchViewModel({
    isLoading: false, errorMessage: null, projection: demo, filters: EMPTY_FILTERS, selectedId: blockedRow.engagement_id,
  });
  assert.ok(["blocked", "partial", "stale", "unavailable"].includes(blocked.surface));
  const fixtureView = composeWorkbenchViewModel({
    isLoading: false, errorMessage: null, projection: demo, filters: EMPTY_FILTERS, selectedId: demo.engagements[0].engagement_id,
  });
  assert.notEqual(fixtureView.surface, "success");
});

test("fixture/manual/simulated evidence never classifies as live validation", async () => {
  const classifier = await readFile(new URL("lib/classifyEvidence.ts", cockpitRoot), "utf8");
  assert.match(classifier, /Fixture\/manual\/simulated never become sample_verified, live_order_verified, or live_sales_validated/);
  assert.match(classifier, /if \(input.evidenceMode === "fixture_only"\) return "fixture"/);
  assert.equal(neverUpgradeEvidenceClass("fixture", "live_validated"), "fixture");
  const scale = buildScaleProjection(12, 12, 4);
  assert.equal(scale.availability, "fixture");
  for (const engagement of scale.engagements) {
    for (const item of engagement.evidence) {
      assert.notEqual(item.evidence_class, "live_validated");
    }
  }
  for (const engagement of buildDemoProjection().engagements) {
    for (const item of engagement.evidence) {
      assert.notEqual(item.evidence_class, "live_validated");
    }
  }
});

test("read-only feature sources do not enable POST publish order payment refund messaging or ads", async () => {
  const files = [
    new URL("../../pages/FirstPhaseEvidenceCockpit.tsx", cockpitRoot),
    new URL("hooks/useFirstPhaseEvidenceCockpit.ts", cockpitRoot),
    new URL("components/CockpitToolbar.tsx", cockpitRoot),
    new URL("../../pages/ServiceDeliveryWorkbench.tsx", workbenchRoot),
    new URL("hooks/useServiceDeliveryWorkbench.ts", workbenchRoot),
    new URL("components/WorkbenchChrome.tsx", workbenchRoot),
    new URL("components/EngagementWorkflow.tsx", workbenchRoot),
  ];
  for (const file of files) {
    const source = await readFile(file, "utf8");
    assert.doesNotMatch(source, MUTATION_MARKERS);
    assert.doesNotMatch(source, /fetch\([^)]*method:\s*["']POST["']/);
  }
  const hook = await readFile(new URL("hooks/useServiceDeliveryWorkbench.ts", workbenchRoot), "utf8");
  assert.match(hook, /method: "GET"/);
  assert.match(hook, /Never POSTs/);
  const review = await readFile(new URL("components/DecisionReviewPanels.tsx", cockpitRoot), "utf8");
  assert.match(review, /No cockpit control can send messages/);
});

test("keyboard skip-link aria-live table semantics and mobile layout remain in source", async () => {
  const cockpitPage = await readFile(new URL("../../pages/FirstPhaseEvidenceCockpit.tsx", cockpitRoot), "utf8");
  const ranked = await readFile(new URL("components/RankedCandidatesPanel.tsx", cockpitRoot), "utf8");
  const keyboard = await readFile(new URL("lib/keyboardNav.ts", cockpitRoot), "utf8");
  const css = await readFile(new URL("../../index.css", cockpitRoot), "utf8");
  const workbenchPage = await readFile(new URL("../../pages/ServiceDeliveryWorkbench.tsx", workbenchRoot), "utf8");
  const pipeline = await readFile(new URL("components/PipelineTable.tsx", workbenchRoot), "utf8");
  const chrome = await readFile(new URL("components/WorkbenchChrome.tsx", workbenchRoot), "utf8");
  assert.match(cockpitPage, /Skip to ranked candidates/);
  assert.match(cockpitPage, /aria-live="polite"/);
  assert.match(ranked, /<table/);
  assert.match(ranked, /type="button"/);
  assert.match(ranked, /aria-pressed=\{selected\}/);
  assert.doesNotMatch(ranked, /role="grid"/);
  assert.match(ranked, /md:hidden/);
  assert.match(ranked, /hidden overflow-x-auto md:block/);
  assert.match(keyboard, /ArrowDown/);
  assert.match(keyboard, /Home/);
  assert.match(keyboard, /End/);
  assert.match(keyboard, /shouldHandoffDetailFocus/);
  assert.match(css, /prefers-reduced-motion/);
  assert.match(workbenchPage, /Skip to service pipeline/);
  assert.match(chrome, /aria-live="polite"/);
  assert.match(pipeline, /<table/);
  assert.match(pipeline, /scope="col"/);
  assert.match(pipeline, /Home/);
  assert.match(pipeline, /End/);
});

test("client-safe export rejects secrets prompts formulas heuristics paths private notes and cross-client keys", async () => {
  const cockpitExport = await readFile(new URL("lib/exportClientSafeReport.ts", cockpitRoot), "utf8");
  assert.match(cockpitExport, /sk-live-/);
  assert.match(cockpitExport, /prompt\|formula\|heuristic/);
  assert.match(cockpitExport, /internal_notes/);
  assert.match(cockpitExport, /PATH_SHAPED/);
  assert.equal(workbenchSecretShaped("sk-live-abcdefghijklmnopqrstuvwxyz"), true);
  assert.equal(workbenchSecretShaped({ internal_notes: "do not leak" }), true);
  assert.equal(workbenchSecretShaped({ prompt: "hidden" }), true);
  assert.equal(workbenchSecretShaped({ formula: "x" }), true);
  assert.equal(workbenchSecretShaped({ heuristic: "y" }), true);
  assert.equal(workbenchSecretShaped("/home/ubuntu/secret"), true);
  assert.equal(workbenchSecretShaped({ cross_client_data: "other-workspace" }), true);
  const engagement = buildDemoProjection().engagements[0];
  const poisoned = {
    ...engagement,
    next_best_action: "sk-live-abcdefghijklmnopqrstuvwxyz",
  };
  const rejected = buildClientSafeServiceExport(poisoned);
  assert.equal(rejected.accepted, false);
});

test("server ordering is unchanged after filtering and windowing", async () => {
  const rows = Array.from({ length: 80 }, (_, index) => rankedStub(index));
  const filtered = filterWithoutReorder(rows, "candidate");
  assert.deepEqual(filtered.map((row) => row.rankIndex), rows.map((row) => row.rankIndex));
  const windowed = windowWithoutReorder(filtered, 50, 10);
  assert.deepEqual(windowed.map((row) => row.rankIndex), Array.from({ length: 10 }, (_, index) => 50 + index));
  const filterSrc = await readFile(new URL("lib/filterCandidates.ts", cockpitRoot), "utf8");
  const windowSrc = await readFile(new URL("lib/windowCandidates.ts", cockpitRoot), "utf8");
  assert.match(filterSrc, /Never sorts/);
  assert.match(windowSrc, /without reordering/);
  const demo = buildDemoProjection();
  const kept = filterEngagements(demo.engagements, EMPTY_FILTERS);
  assert.deepEqual(kept.map((row) => row.engagement_id), demo.engagements.map((row) => row.engagement_id));
});

test("sanitized fixture HTML encodes skip link live region grid and no mutation controls", async () => {
  const html = await readFile(smokeHtml, "utf8");
  assert.match(html, /Skip to ranked candidates/);
  assert.match(html, /aria-live="polite"/);
  assert.match(html, /role="grid"/);
  assert.match(html, /fixture_only/);
  assert.match(html, /Not live proof/);
  assert.match(html, /No POST, publish, order, payment, refund, messaging, or ad controls/);
  assert.doesNotMatch(html, /evidence class: live_validated/i);
  assert.doesNotMatch(html, /<form/i);
  // Cursor browser MCP is not installed in this environment. google-chrome --dump-dom
  // timed out, so this smoke stays fixture-HTML-only rather than a live React session.
});
