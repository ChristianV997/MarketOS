import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { adaptServiceProjection } from "../src/features/service-delivery-workbench/lib/adaptServiceProjection.ts";
import { composeWorkbenchViewModel } from "../src/features/service-delivery-workbench/lib/composeWorkbenchViewModel.ts";
import { EMPTY_FILTERS } from "../src/features/service-delivery-workbench/lib/filterEngagements.ts";
import { buildDemoProjection } from "../src/features/service-delivery-workbench/fixtures/buildFixtures.ts";
import { buildProducerPlaneEnvelope } from "../src/features/service-delivery-workbench/fixtures/producerPlaneEnvelope.ts";

function viewFor(projection, extra = {}) {
  return composeWorkbenchViewModel({
    isLoading: false,
    errorMessage: null,
    projection,
    filters: EMPTY_FILTERS,
    selectedId: projection.engagements[0]?.engagement_id ?? null,
    ...extra,
  });
}

test("cross-surface evidence matrix: workbench GET slot is not envelope proof", () => {
  const fixtureSource = { ...buildDemoProjection(), availability: "fixture" };
  const fixture = adaptServiceProjection(fixtureSource);
  assert.equal(fixture.rejected, false);
  const fixtureView = viewFor(fixture.projection);
  assert.notEqual(fixtureView.surface, "success");
  assert.equal(fixtureView.envelopeAvailability, "fixture");
  assert.equal(fixtureView.liveEndpointStatus, "unavailable");
  assert.match(fixtureView.statusMessage, /Envelope: fixture/);
  assert.match(fixtureView.statusMessage, /GET slot: unavailable/);
  assert.ok(fixture.projection.engagements[0].evidence.every((item) => item.evidence_class !== "live_validated"));

  const servedFixture = adaptServiceProjection({
    ...fixtureSource,
    live_endpoint_status: "available_read_only",
  });
  const servedView = viewFor(servedFixture.projection);
  assert.equal(servedView.liveEndpointStatus, "available_read_only");
  assert.equal(servedView.envelopeAvailability, "fixture");
  assert.notEqual(servedView.surface, "success");
  assert.match(servedView.statusMessage, /not live_validated/);

  const missing = composeWorkbenchViewModel({
    isLoading: false,
    errorMessage: "Canonical GET unavailable (Failed to fetch). This is not a fixture success state.",
    projection: null,
    filters: EMPTY_FILTERS,
    selectedId: null,
  });
  assert.equal(missing.surface, "unavailable");
  assert.equal(missing.envelopeAvailability, "unknown");
  assert.equal(missing.liveEndpointStatus, "unavailable");

  const plane = adaptServiceProjection(buildProducerPlaneEnvelope());
  const manual = viewFor(plane.projection);
  assert.equal(manual.envelopeAvailability, "manual_import");
  assert.notEqual(manual.surface, "success");
  assert.match(manual.statusMessage, /manual_import/);
  if (manual.exportPreview?.accepted) {
    assert.ok(manual.exportPreview.payload);
    assert.doesNotMatch(JSON.stringify(manual.exportPreview.payload), /live_validated/);
  }

  const staleSource = adaptServiceProjection({
    ...fixtureSource,
    availability: "partial",
    engagements: fixtureSource.engagements.map((row, index) => index === 0 ? { ...row, stale: true } : row),
  });
  const staleView = viewFor(staleSource.projection);
  assert.ok(["stale", "partial", "blocked"].includes(staleView.surface));
  assert.notEqual(staleView.surface, "success");
});

test("workbench chrome splits GET slot from envelope vocabulary", async () => {
  const chrome = await readFile(new URL("../src/features/service-delivery-workbench/components/WorkbenchChrome.tsx", import.meta.url), "utf8");
  const workflow = await readFile(new URL("../src/features/service-delivery-workbench/components/EngagementWorkflow.tsx", import.meta.url), "utf8");
  const page = await readFile(new URL("../src/pages/ServiceDeliveryWorkbench.tsx", import.meta.url), "utf8");
  assert.match(chrome, /GET slot:/);
  assert.match(chrome, /Envelope:/);
  assert.match(chrome, /Not live validated/);
  assert.match(workflow, /Redaction-pass draft preview/);
  assert.doesNotMatch(workflow, /Accepted client-safe preview/);
  assert.doesNotMatch(page, /method:\s*["']POST["']/);
});
