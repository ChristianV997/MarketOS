import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { composeStrategyView } from "../src/features/marketing-strategy-workbench/lib/composeStrategyView.ts";
import { buildClientSafeStrategyExport } from "../src/features/marketing-strategy-workbench/lib/exportClientSafeStrategy.ts";
import {
  buildComplete,
  buildConflicting,
  buildNoEvidence,
  buildPartial,
  buildStale,
} from "../src/features/marketing-strategy-workbench/fixtures/buildStrategyFixtures.ts";

const componentUrl = new URL("../src/features/marketing-strategy-workbench/components/StrategyWorkbench.tsx", import.meta.url);

test("complete service, goods, and hybrid drafts stay unexecuted", () => {
  for (const kind of ["service", "goods", "hybrid"]) {
    const view = composeStrategyView(buildComplete(kind));
    assert.equal(view.draft_only, true);
    assert.equal(view.executed_campaign, false);
    assert.equal(view.offer_kind, kind);
    assert.match(view.banner, /not published|Not an executed|not an executed/i);
  }
});

test("partial, stale, conflicting, and no-evidence claims stay labeled", () => {
  const partial = composeStrategyView(buildPartial());
  assert.equal(partial.surface, "partial");
  assert.equal(partial.publicity.length, 0);
  const stale = composeStrategyView(buildStale());
  assert.ok(stale.claims.some((claim) => claim.status === "stale"));
  assert.ok(stale.claims.some((claim) => claim.evidence_labels.includes("Stale")));
  const conflict = composeStrategyView(buildConflicting());
  assert.ok(conflict.claims.some((claim) => claim.status === "conflicting"));
  const none = composeStrategyView(buildNoEvidence());
  assert.ok(none.claims.every((claim) => claim.status === "needs_review"));
});

test("missing packet is unavailable and not a campaign", () => {
  const view = composeStrategyView(null, true);
  assert.equal(view.surface, "unavailable");
  assert.equal(view.executed_campaign, false);
  assert.match(view.banner, /not an executed campaign/i);
});

test("client-safe export drops internal briefs and rejects secret-shaped copy", () => {
  const packet = buildComplete("service");
  const exported = buildClientSafeStrategyExport(packet);
  assert.equal(exported.ok, true);
  const encoded = JSON.stringify(exported.body);
  assert.doesNotMatch(encoded, /internal prompt hidden/i);
  assert.equal(exported.body.executed_campaign, false);
  assert.match(exported.body.budget_assumptions[0], /assumption/);
  packet.positioning = "api_key=secret-value";
  const rejected = buildClientSafeStrategyExport(packet);
  assert.equal(rejected.ok, false);
});

test("component source has no mutation controls and keeps semantic review structure", async () => {
  const source = await readFile(componentUrl, "utf8");
  assert.match(source, /Draft only/);
  assert.match(source, /Skip to claims/);
  assert.match(source, /aria-live="polite"/);
  assert.match(source, /<table/);
  assert.match(source, /overflow-x-auto/);
  assert.match(source, /motion-reduce:transition-none/);
  assert.match(source, /type="button"/);
  assert.match(source, /assumption/);
  assert.doesNotMatch(source, /method:\s*["']POST["']/);
  assert.doesNotMatch(source, /fetch\(|createCampaign/);
});
