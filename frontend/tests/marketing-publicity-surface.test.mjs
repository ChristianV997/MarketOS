import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { composePublicityScenario, rejectedLaunchProbe } from "../src/features/marketing-publicity-surface/lib/composePublicityScenario.ts";
import {
  buildComplete,
  buildNoEvidence,
  buildStale,
} from "../src/features/marketing-strategy-workbench/fixtures/buildStrategyFixtures.ts";

test("publicity scenario keeps provenance and never treats labels as proof", () => {
  const scenario = composePublicityScenario(buildComplete("hybrid"));
  assert.equal(scenario.draft_only, true);
  assert.equal(scenario.executed_campaign, false);
  assert.equal(scenario.proof, false);
  assert.ok(scenario.claims.every((claim) => claim.provenance === "packet_evidence" && claim.proof === false));
  assert.ok(scenario.claims.some((claim) => claim.status === "needs_review"));
  assert.ok(scenario.approvals.every((item) => item.granted === false));
  assert.equal(scenario.research.ok, false);
  assert.match(scenario.banner, /not proof/i);
});

test("stale and no-evidence packets stay unproven", () => {
  const stale = composePublicityScenario(buildStale());
  assert.ok(stale.claims.some((claim) => claim.status === "stale"));
  assert.ok(stale.claims.every((claim) => claim.proof === false));
  const none = composePublicityScenario(buildNoEvidence());
  assert.ok(none.claims.every((claim) => claim.status === "needs_review"));
});

test("research launch authorization is rejected with the production reason", async () => {
  assert.equal(rejectedLaunchProbe(), "launch_authorized_rejected");
  const overlay = await readFile(
    new URL("../src/features/first-phase-cockpit/lib/overlayResearchToDecision.ts", import.meta.url),
    "utf8",
  );
  assert.match(overlay, /launch_authorized_rejected/);
});

test("surface markup is responsive, labeled, and free of mutation calls", async () => {
  const source = await readFile(
    new URL("../src/features/marketing-publicity-surface/components/PublicitySurface.tsx", import.meta.url),
    "utf8",
  );
  assert.match(source, /md:grid-cols-2/);
  assert.match(source, /Skip to human approvals/);
  assert.match(source, /aria-live="polite"/);
  assert.match(source, /overflow-x-auto/);
  assert.match(source, /motion-reduce:transition-none/);
  assert.match(source, /Kill, iterate, and scale/);
  assert.match(source, /Legal and privacy blockers/);
  assert.doesNotMatch(source, /fetch\(|method:\s*["']POST["']/);
});
