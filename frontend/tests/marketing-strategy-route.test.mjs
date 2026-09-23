import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { composePublicityScenario } from "../src/features/marketing-publicity-surface/lib/composePublicityScenario.ts";
import { buildComplete, buildConflicting, buildPartial, buildStale } from "../src/features/marketing-strategy-workbench/fixtures/buildStrategyFixtures.ts";

test("route page states stay draft-only and unlaunched", () => {
  for (const packet of [buildComplete("hybrid"), buildPartial(), buildStale(), buildConflicting(), null]) {
    const scenario = composePublicityScenario(packet);
    assert.equal(scenario.draft_only, true);
    assert.equal(scenario.executed_campaign, false);
    assert.equal(scenario.proof, false);
    if (scenario.research.ok) assert.equal(scenario.research.launch_authorized, false);
  }
  assert.equal(composePublicityScenario(null).surface, "unavailable");
  assert.equal(composePublicityScenario(buildPartial()).surface, "partial");
  assert.equal(composePublicityScenario(buildStale()).surface, "stale");
  assert.equal(composePublicityScenario(buildConflicting()).surface, "conflicting");
});

test("shell registers one strategy route and no campaign mutation", async () => {
  const main = await readFile(new URL("../src/main.tsx", import.meta.url), "utf8");
  const sidebar = await readFile(new URL("../src/components/layout/Sidebar.tsx", import.meta.url), "utf8");
  const page = await readFile(new URL("../src/features/marketing-strategy-workbench/MarketingStrategyPage.tsx", import.meta.url), "utf8");
  assert.equal(main.split("/operator/marketing-strategy").length - 1, 1);
  assert.match(sidebar, /\/operator\/marketing-strategy/);
  assert.match(page, /live_validated=false/);
  assert.match(page, /launch_authorized=false/);
  assert.match(page, /StrategyWorkbench/);
  assert.doesNotMatch(page, /<PublicitySurface/);
  assert.doesNotMatch(page, /method:\s*["']POST["']|fetch\(/);
  assert.doesNotMatch(main, /method:\s*["']POST["']/);
});
