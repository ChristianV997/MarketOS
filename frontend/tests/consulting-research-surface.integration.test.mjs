import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { adaptResearchSurface } from "../src/features/consulting-research-surface/lib/adaptResearchSurface.ts";
import { composeResearchSurface } from "../src/features/consulting-research-surface/lib/composeResearchSurface.ts";
import { buildSurfaceFixture } from "../src/features/consulting-research-surface/fixtures/surfaceFixture.ts";
import { ingestLocalResearchReportJson } from "../src/features/consulting-research-surface/lib/loadLocalResearchReport.ts";
import { buildClientSafeSurfaceExport } from "../src/features/consulting-research-surface/lib/exportResearchSurface.ts";

test("stale fixture without blockers is stale, not success", () => {
  const packet = buildSurfaceFixture();
  packet.blockers = [];
  packet.sections[2].rows[0].fresh = false;
  const adapted = adaptResearchSurface(packet);
  const view = composeResearchSurface({
    loading: false,
    errorMessage: null,
    model: adapted.model,
    rejected: false,
    selectedSectionId: "competitor",
  });
  assert.equal(view.state, "stale");
  assert.equal(view.selectedSectionId, "competitor");
  assert.equal(view.exportPreview.accepted, true);
  assert.equal(view.exportPreview.payload.next_action_executes, false);
});

test("secret packet does not export", () => {
  const packet = buildSurfaceFixture();
  packet.display_name = "sk-" + "live-abcdefghijklmnopqrstuvwxyz";
  const adapted = adaptResearchSurface(packet);
  assert.equal(adapted.rejected, true);
  const view = composeResearchSurface({
    loading: false,
    errorMessage: null,
    model: adapted.model,
    rejected: true,
    selectedSectionId: null,
  });
  assert.equal(view.state, "unavailable");
  assert.equal(view.exportPreview.accepted, false);
});

test("browser-shaped local market research load reaches export-safe draft view", async () => {
  const sampleText = await readFile(
    new URL("../src/features/consulting-research-surface/fixtures/market_research_report_sample.json", import.meta.url),
    "utf8",
  );
  const loaded = ingestLocalResearchReportJson(sampleText);
  assert.equal(loaded.ok, true);
  if (!loaded.ok) return;
  const adapted = adaptResearchSurface(loaded.packet);
  assert.equal(adapted.rejected, false);
  const view = composeResearchSurface({
    loading: false,
    errorMessage: null,
    model: adapted.model,
    rejected: false,
    selectedSectionId: null,
  });
  assert.ok(["blocked", "stale", "partial", "empty", "unavailable"].includes(view.state));
  assert.notEqual(view.state, "success");
  assert.equal(view.launchAuthorized, false);
  const exported = buildClientSafeSurfaceExport(adapted.model);
  assert.equal(exported.payload?.launch_authorized, false);
  assert.equal(exported.payload?.live_validated, false);
  assert.equal(exported.payload?.draft_only, true);
});
