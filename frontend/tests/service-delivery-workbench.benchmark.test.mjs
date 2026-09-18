import assert from "node:assert/strict";
import { test } from "node:test";

import { composeWorkbenchViewModel } from "../src/features/service-delivery-workbench/lib/composeWorkbenchViewModel.ts";
import { buildClientSafeServiceExport } from "../src/features/service-delivery-workbench/lib/exportClientSafeEngagement.ts";
import { EMPTY_FILTERS, filterEngagements } from "../src/features/service-delivery-workbench/lib/filterEngagements.ts";
import { adaptServiceProjection } from "../src/features/service-delivery-workbench/lib/adaptServiceProjection.ts";
import { buildOneClientProjection, buildScaleProjection, buildTenClientProjection } from "../src/features/service-delivery-workbench/fixtures/buildFixtures.ts";

function timed(label, fn) {
  const start = performance.now();
  const value = fn();
  const elapsed = performance.now() - start;
  return { label, elapsed, value };
}

test("deterministic performance budget for normalize/filter/compose/export", () => {
  const one = timed("one-client", () => buildOneClientProjection());
  const ten = timed("ten-clients", () => buildTenClientProjection());
  const scale = timed("hundred-engagements", () => buildScaleProjection(100, 40, 20));

  const normalize = timed("normalize-100", () => adaptServiceProjection(scale.value));
  const filter = timed("filter-100", () => filterEngagements(scale.value.engagements, {
    ...EMPTY_FILTERS,
    query: "northwind",
  }));
  const compose = timed("compose-100", () => composeWorkbenchViewModel({
    isLoading: false,
    errorMessage: null,
    projection: scale.value,
    filters: EMPTY_FILTERS,
    selectedId: scale.value.engagements[0].engagement_id,
  }));
  const exportAll = timed("export-100", () => scale.value.engagements.map((item) => buildClientSafeServiceExport(item)));

  const report = { one, ten, scale, normalize, filter, compose, exportAll };
  for (const row of Object.values(report)) {
    assert.ok(row.elapsed < 1500, `${row.label} exceeded 1500ms: ${row.elapsed}`);
  }
  assert.equal(normalize.value.projection.engagements.length, 100);
  assert.ok(filter.value.length >= 1);
  assert.equal(compose.value.filtered.length, 100);
  assert.equal(exportAll.value.length, 100);
  // No virtualization required under this budget.
  assert.ok(compose.elapsed < 250, `compose should stay cheap without virtualization: ${compose.elapsed}`);
});
