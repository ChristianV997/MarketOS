import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const featureRoot = new URL("../src/features/first-phase-cockpit/", import.meta.url);

test("composeCockpitViewModel preserves backend candidate order without re-ranking", async () => {
  const source = await readFile(new URL("lib/composeCockpitViewModel.ts", featureRoot), "utf8");
  assert.doesNotMatch(source, /\.sort\(/);
  assert.match(source, /benchmark\.candidates\.map\(\(item, rankIndex\)/);
  assert.match(source, /isTopCandidate: item\.candidate\.candidate_id === benchmark\.top_candidate_id/);
});

test("composeCockpitViewModel marks unavailable endpoints explicitly", async () => {
  const source = await readFile(new URL("lib/composeCockpitViewModel.ts", featureRoot), "utf8");
  assert.match(source, /phase1_readiness_unavailable/);
  assert.match(source, /benchmark_matrix_unavailable/);
  assert.match(source, /public_market_benchmark_unavailable/);
  assert.match(source, /research_portfolio_unavailable/);
  assert.match(source, /consumer_attention_api_unavailable/);
  assert.match(source, /status: "unavailable"/);
});

test("demo fixture documents trustos and governor slots without secrets", async () => {
  const source = await readFile(new URL("fixtures/demoPacket.ts", featureRoot), "utf8");
  assert.doesNotMatch(source, /sk-live-|ghp_|authorization/i);
  assert.match(source, /id: "trustos"/);
  assert.match(source, /id: "governor"/);
  assert.match(source, /id: "approval_ledger"/);
  assert.doesNotMatch(source, /password|secret|api_key/i);
});

test("first-phase cockpit page and route are wired without modifying API client authority", async () => {
  const mainSource = await readFile(new URL("../src/main.tsx", import.meta.url), "utf8");
  const pageSource = await readFile(new URL("../src/pages/FirstPhaseEvidenceCockpit.tsx", import.meta.url), "utf8");
  const hookSource = await readFile(new URL("hooks/useFirstPhaseEvidenceCockpit.ts", featureRoot), "utf8");
  const apiClientSource = await readFile(new URL("../src/lib/canonicalEventsApi.ts", import.meta.url), "utf8");

  assert.match(mainSource, /\/operator\/first-phase/);
  assert.match(pageSource, /useFirstPhaseEvidenceCockpit/);
  assert.match(hookSource, /usePhase1Readiness/);
  assert.match(hookSource, /useBenchmarkMatrix/);
  assert.match(hookSource, /usePublicMarketBenchmark/);
  assert.match(hookSource, /useResearchPortfolios/);
  assert.doesNotMatch(pageSource, /fetchPhase1Readiness/);
  assert.doesNotMatch(pageSource, /new WebSocket/);
  assert.doesNotMatch(apiClientSource, /first-phase-cockpit/);
});

test("cockpit components render advisory states without mutation authority", async () => {
  const banner = await readFile(new URL("components/CockpitStatusBanner.tsx", featureRoot), "utf8");
  const ranked = await readFile(new URL("components/RankedCandidatesPanel.tsx", featureRoot), "utf8");
  const control = await readFile(new URL("components/ControlPlanePanel.tsx", featureRoot), "utf8");
  const page = await readFile(new URL("../src/pages/FirstPhaseEvidenceCockpit.tsx", import.meta.url), "utf8");

  assert.doesNotMatch(page, /onClick|button type="submit"|fetch\(/);
  assert.match(banner, /loading|empty|blocked|unavailable|stale|success/i);
  assert.match(ranked, /rankIndex/);
  assert.match(control, /TrustOS/);
  assert.match(control, /Governor/);
  assert.match(control, /No launch, ads, orders, payment, publishing, or messaging authority/);
});
