import assert from "node:assert/strict";
import { test } from "node:test";

import { adaptResearchSurface } from "../src/features/consulting-research-surface/lib/adaptResearchSurface.ts";
import { composeResearchSurface } from "../src/features/consulting-research-surface/lib/composeResearchSurface.ts";
import { buildSurfaceFixture } from "../src/features/consulting-research-surface/fixtures/surfaceFixture.ts";

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
