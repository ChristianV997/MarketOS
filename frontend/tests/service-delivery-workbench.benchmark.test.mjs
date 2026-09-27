import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { test } from "node:test";

import { composeWorkbenchViewModel } from "../src/features/service-delivery-workbench/lib/composeWorkbenchViewModel.ts";
import { buildClientSafeServiceExport } from "../src/features/service-delivery-workbench/lib/exportClientSafeEngagement.ts";
import { EMPTY_FILTERS, filterEngagements } from "../src/features/service-delivery-workbench/lib/filterEngagements.ts";
import { adaptServiceProjection } from "../src/features/service-delivery-workbench/lib/adaptServiceProjection.ts";
import { normalizeWorkbenchRenderModel } from "../src/features/service-delivery-workbench/lib/normalizeWorkbenchRenderModel.ts";
import { buildOneClientProjection, buildScaleProjection, buildTenClientProjection } from "../src/features/service-delivery-workbench/fixtures/buildFixtures.ts";

function timed(label, fn) {
  const start = performance.now();
  const value = fn();
  const elapsed = performance.now() - start;
  return { label, elapsed, value };
}

function digest(value) {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

test("observed normalize/filter/compose/export timings for 1/10/100/500/1000/5000/10000 (no ranking, replay-stable)", () => {
  const sizes = [1, 10, 100, 500, 1000, 5000, 10000];
  const report = {};
  for (const size of sizes) {
    const built = size === 1
      ? timed(`build-${size}`, () => buildOneClientProjection())
      : size === 10
        ? timed(`build-${size}`, () => buildTenClientProjection())
        : timed(`build-${size}`, () => buildScaleProjection(size, 8, 4));
    const normalize = timed(`normalize-${size}`, () => adaptServiceProjection(built.value));
    const filtered = timed(`filter-${size}`, () => filterEngagements(normalize.value.projection.engagements, {
      ...EMPTY_FILTERS,
      query: size === 1 ? "northwind" : "",
    }));
    const compose = timed(`compose-${size}`, () => composeWorkbenchViewModel({
      isLoading: false,
      errorMessage: null,
      projection: normalize.value.projection,
      filters: EMPTY_FILTERS,
      selectedId: normalize.value.projection.engagements[0]?.engagement_id ?? null,
    }));
    const exported = timed(`export-${size}`, () =>
      compose.value.filtered.map((item) => buildClientSafeServiceExport(item)));
    const snapshot = normalizeWorkbenchRenderModel(normalize.value.projection);
    const replay = digest(snapshot);
    assert.deepEqual(
      snapshot.engagement_ids_in_order,
      (size === 1 ? buildOneClientProjection() : size === 10 ? buildTenClientProjection() : buildScaleProjection(size, 8, 4))
        .engagements.map((item) => item.engagement_id),
    );
    assert.equal(digest(snapshot), replay);
    assert.equal(snapshot.frontend_calculates, true);
    assert.notEqual(compose.value.surface, "success");
    assert.ok(compose.value.filtered.length <= 500);
    if (size > 500) assert.equal(compose.value.bounded, true);
    report[size] = {
      build_ms: Number(built.elapsed.toFixed(3)),
      normalize_ms: Number(normalize.elapsed.toFixed(3)),
      filter_ms: Number(filtered.elapsed.toFixed(3)),
      compose_ms: Number(compose.elapsed.toFixed(3)),
      export_ms: Number(exported.elapsed.toFixed(3)),
      replay_sha256: replay,
    };
  }
  process.stdout.write(`${JSON.stringify({ service_workbench_perf: report }, null, 2)}\n`);
});
