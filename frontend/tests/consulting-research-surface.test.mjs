import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { adaptResearchSurface, normalizeClass } from "../src/features/consulting-research-surface/lib/adaptResearchSurface.ts";
import { composeResearchSurface, moveSelection, sectionIds } from "../src/features/consulting-research-surface/lib/composeResearchSurface.ts";
import { buildClientSafeSurfaceExport } from "../src/features/consulting-research-surface/lib/exportResearchSurface.ts";
import { buildSurfaceFixture } from "../src/features/consulting-research-surface/fixtures/surfaceFixture.ts";

function viewOf(packet, extra = {}) {
  const adapted = adaptResearchSurface(packet);
  return composeResearchSurface({
    loading: false,
    errorMessage: null,
    model: adapted.model,
    rejected: adapted.rejected,
    selectedSectionId: null,
    ...extra,
  });
}

test("fixture integration keeps order, conflicts, missing data, and non-success", () => {
  const packet = buildSurfaceFixture();
  const adapted = adaptResearchSurface(packet);
  assert.equal(adapted.rejected, false);
  assert.deepEqual(sectionIds(adapted.model), ["demand", "customer", "competitor", "supplier", "logistics", "economics"]);
  const view = viewOf(packet);
  assert.equal(view.state, "blocked");
  assert.equal(view.launchAuthorized, false);
  assert.equal(view.model.draft_only, true);
  assert.equal(view.model.live_validated, false);
  assert.equal(view.model.launch_authorized, false);
  assert.equal(view.fixtureIsSuccess, false);
  assert.equal(view.conflicts[0].section_id, "demand");
  assert.deepEqual(view.missing, [{ section_id: "supplier", field: "supplier_legal_name" }]);
  const exported = buildClientSafeSurfaceExport(adapted.model);
  assert.equal(exported.payload.draft_only, true);
  assert.equal(exported.payload.live_validated, false);
  assert.equal(exported.payload.launch_authorized, false);
  const { omitted, ...body } = exported.payload;
  assert.ok(omitted.includes("credentials"));
  assert.doesNotMatch(JSON.stringify(body), /internal_prompt|sk-live-/);
});

test("live claims, empty packets, loading, and errors stay honest", () => {
  assert.equal(normalizeClass("live_validated"), "unavailable");
  assert.equal(normalizeClass("observed"), "observed");
  const packet = buildSurfaceFixture();
  packet.sections[0].rows[0].evidence_class = "live_validated";
  packet.blockers = [];
  packet.sections.forEach((section) => { section.rows[0].fresh = null; });
  const view = viewOf(packet);
  assert.equal(view.model.sections[0].rows[0].evidence_class, "unavailable");
  assert.notEqual(view.state, "success");
  const empty = buildSurfaceFixture();
  empty.sections = [];
  empty.blockers = [];
  assert.equal(viewOf(empty).state, "empty");
  const loading = composeResearchSurface({
    loading: true,
    errorMessage: null,
    model: adaptResearchSurface(buildSurfaceFixture()).model,
    rejected: false,
    selectedSectionId: null,
  });
  assert.equal(loading.state, "loading");
  assert.equal(adaptResearchSurface({ version: "nope" }).reason, "unsupported_version");
});

test("keyboard stays in source order and source has no mutation client", async () => {
  const order = ["demand", "customer", "supplier"];
  assert.equal(moveSelection(order, "demand", "ArrowDown"), "customer");
  assert.equal(moveSelection(order, "supplier", "Home"), "demand");
  const source = await readFile(new URL("../src/features/consulting-research-surface/components/ConsultingResearchSurface.tsx", import.meta.url), "utf8");
  const page = await readFile(new URL("../src/features/consulting-research-surface/ConsultingResearchSurfacePage.tsx", import.meta.url), "utf8");
  assert.match(source, /aria-live="polite"/);
  assert.match(source, /<table/);
  assert.match(source, /motion-reduce:transition-none/);
  assert.match(source, /overflow-x-auto/);
  assert.doesNotMatch(source, /method:\s*["']POST["']|fetch\(/);
  assert.doesNotMatch(page, /Shell|Sidebar/);
});
