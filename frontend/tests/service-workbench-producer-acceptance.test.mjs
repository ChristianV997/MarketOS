import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { adaptServiceProjection } from "../src/features/service-delivery-workbench/lib/adaptServiceProjection.ts";
import {
  WORKBENCH_FILTER_WINDOW,
  composeWorkbenchViewModel,
  moveSelection,
} from "../src/features/service-delivery-workbench/lib/composeWorkbenchViewModel.ts";
import { buildClientSafeServiceExport, containsSecretShapedValue } from "../src/features/service-delivery-workbench/lib/exportClientSafeEngagement.ts";
import { EMPTY_FILTERS, filterEngagements } from "../src/features/service-delivery-workbench/lib/filterEngagements.ts";
import { buildProducerPlaneEnvelope } from "../src/features/service-delivery-workbench/fixtures/producerPlaneEnvelope.ts";
import { buildScaleProjection } from "../src/features/service-delivery-workbench/fixtures/buildFixtures.ts";

const REQUIRED_LIFECYCLES = [
  "data_inadequate",
  "draft_ready",
  "client_review",
  "revision_requested",
  "approved",
  "delivered",
  "cancelled",
  "rejected",
];

function viewFor(projection, selectedId = null) {
  return composeWorkbenchViewModel({
    isLoading: false,
    errorMessage: null,
    projection,
    filters: EMPTY_FILTERS,
    selectedId,
  });
}

test("loading empty blocked unavailable partial stale surfaces never become success", () => {
  assert.equal(composeWorkbenchViewModel({
    isLoading: true, errorMessage: null, projection: null, filters: EMPTY_FILTERS, selectedId: null,
  }).surface, "loading");
  assert.equal(composeWorkbenchViewModel({
    isLoading: false, errorMessage: null, projection: null, filters: EMPTY_FILTERS, selectedId: null,
  }).surface, "empty");
  assert.equal(composeWorkbenchViewModel({
    isLoading: false, errorMessage: "GET failed", projection: null, filters: EMPTY_FILTERS, selectedId: null,
  }).surface, "unavailable");

  const adapted = adaptServiceProjection(buildProducerPlaneEnvelope());
  const blocked = viewFor(adapted.projection, "eng-prod-1");
  assert.equal(blocked.surface, "blocked");
  assert.match(blocked.statusMessage, /data_inadequate/);

  const staleProjection = adaptServiceProjection(buildProducerPlaneEnvelope({
    engagements: [{
      ...buildProducerPlaneEnvelope().engagements[1],
      stale: true,
    }],
  })).projection;
  assert.equal(viewFor(staleProjection).surface, "stale");

  const unavailable = adaptServiceProjection({ schema_version: "nope-v9" });
  assert.equal(unavailable.projection.availability, "unavailable");
  assert.notEqual(viewFor(unavailable.projection).surface, "success");
});

test("#275 producer envelope is consumed by version without a second schema", () => {
  const raw = buildProducerPlaneEnvelope({
    live_endpoint_status: "available_read_only",
  });
  const result = adaptServiceProjection(raw);
  assert.equal(result.rejected, false);
  assert.equal(result.projection.input_contract, "service-delivery-plane-v1");
  assert.equal(result.projection.live_endpoint_status, "available_read_only");
  assert.match(result.projection.diagnostics.join(" "), /available read-only/);
  assert.ok(!result.projection.diagnostics.join(" ").includes("workbench is unavailable;"));
  const view = viewFor(result.projection, "eng-prod-2");
  assert.equal(view.surface, "partial");
  assert.notEqual(view.surface, "success");
  assert.equal(view.liveEndpointUnavailable, false);
  assert.match(view.statusMessage, /Selected lifecycle: draft_ready/);
});

test("required lifecycle states survive adapter mapping in source order", () => {
  const result = adaptServiceProjection(buildProducerPlaneEnvelope());
  const states = result.projection.engagements.map((row) => row.lifecycle_state);
  assert.deepEqual(states, REQUIRED_LIFECYCLES);
  assert.deepEqual(
    result.projection.engagements.map((row) => row.engagement_id),
    buildProducerPlaneEnvelope().engagements.map((row) => row.engagement_id),
  );
});

test("endpoint unavailable never becomes success even with producer rows", () => {
  const result = adaptServiceProjection(buildProducerPlaneEnvelope({
    live_endpoint_status: "unavailable",
  }));
  const view = viewFor(result.projection, "eng-prod-2");
  assert.notEqual(view.surface, "success");
  assert.equal(view.liveEndpointUnavailable, true);
});

test("fixture/manual/simulated evidence never becomes live_validated from producer claims", () => {
  const poisoned = buildProducerPlaneEnvelope();
  poisoned.engagements[1].evidence_set[0].evidence_class = "live_validated";
  poisoned.engagements[1].evidence_set[0].base_class = "fixture";
  const result = adaptServiceProjection(poisoned);
  assert.notEqual(result.projection.engagements[1].evidence[0].evidence_class, "live_validated");
  const simulated = adaptServiceProjection({
    schema_version: "service-engagement-projection-v1",
    availability: "fixture",
    engagements: [{
      engagement_id: "eng-sim",
      service_id: "launch-draft-pack",
      lifecycle_state: "draft_ready",
      evidence: [{ evidence_id: "e1", evidence_class: "live_validated", base_class: "simulated" }],
    }],
  });
  assert.equal(simulated.projection.engagements[0].evidence[0].evidence_class, "simulated");
});

test("backend economics are copied and never recalculated", () => {
  const result = adaptServiceProjection(buildProducerPlaneEnvelope());
  const approved = result.projection.engagements.find((row) => row.lifecycle_state === "approved");
  assert.equal(approved.economics.frontend_calculates, false);
  assert.equal(approved.economics.authority, "backend_service_economics");
  assert.equal(approved.economics.fee.amount_label, "1200.00");
  assert.equal(approved.economics.contribution.amount_label, "410.00");
  assert.equal(approved.economics.fee.display_only, true);
});

test("client-safe export rejects prompts formulas heuristics secrets source code paths private notes and cross-client values", () => {
  const engagement = adaptServiceProjection(buildProducerPlaneEnvelope()).projection.engagements[1];
  assert.equal(containsSecretShapedValue({ prompt: "hidden" }), true);
  assert.equal(containsSecretShapedValue({ formula: "x*y" }), true);
  assert.equal(containsSecretShapedValue({ heuristic: "rank" }), true);
  assert.equal(containsSecretShapedValue("sk-live-abcdefghijklmnopqrstuvwxyz"), true);
  assert.equal(containsSecretShapedValue({ source_code: "print(1)" }), true);
  assert.equal(containsSecretShapedValue("/home/ubuntu/marketos/secret"), true);
  assert.equal(containsSecretShapedValue({ internal_notes: "no" }), true);
  assert.equal(containsSecretShapedValue({ cross_client_data: "other" }), true);
  const secretExport = buildClientSafeServiceExport({
    ...engagement,
    next_best_action: { ...engagement.next_best_action, action: "sk-live-abcdefghijklmnopqrstuvwxyz" },
  });
  assert.equal(secretExport.accepted, false);
  const inadequate = adaptServiceProjection(buildProducerPlaneEnvelope()).projection.engagements[0];
  assert.equal(buildClientSafeServiceExport(inadequate).accepted, false);
});

test("filters preserve producer order and do not rerank", () => {
  const rows = adaptServiceProjection(buildProducerPlaneEnvelope()).projection.engagements;
  const filtered = filterEngagements(rows, EMPTY_FILTERS);
  assert.deepEqual(filtered.map((row) => row.engagement_id), rows.map((row) => row.engagement_id));
  const launch = filterEngagements(rows, { ...EMPTY_FILTERS, serviceId: "launch-draft-pack" });
  const original = rows.filter((row) => row.service_id === "launch-draft-pack");
  assert.deepEqual(launch.map((row) => row.engagement_id), original.map((row) => row.engagement_id));
});

test("keyboard helper stays inside the filtered window", () => {
  const rows = adaptServiceProjection(buildProducerPlaneEnvelope()).projection.engagements;
  assert.equal(moveSelection(rows, rows[0].engagement_id, 1), rows[1].engagement_id);
  assert.equal(moveSelection(rows, rows[0].engagement_id, -20), rows[0].engagement_id);
  assert.equal(moveSelection(rows, rows[2].engagement_id, 99), rows[rows.length - 1].engagement_id);
});

test("large lists remain bounded at the compose window", () => {
  const scale = buildScaleProjection(WORKBENCH_FILTER_WINDOW + 20, 4, 2);
  const view = viewFor(scale);
  assert.equal(view.filtered.length, WORKBENCH_FILTER_WINDOW);
  assert.equal(view.bounded, true);
  assert.deepEqual(
    view.filtered.map((row) => row.engagement_id),
    scale.engagements.slice(0, WORKBENCH_FILTER_WINDOW).map((row) => row.engagement_id),
  );
});

test("keyboard skip-link live region table and mobile semantics remain in source", async () => {
  const page = await readFile(new URL("../src/pages/ServiceDeliveryWorkbench.tsx", import.meta.url), "utf8");
  const table = await readFile(new URL("../src/features/service-delivery-workbench/components/PipelineTable.tsx", import.meta.url), "utf8");
  const chrome = await readFile(new URL("../src/features/service-delivery-workbench/components/WorkbenchChrome.tsx", import.meta.url), "utf8");
  assert.match(page, /Skip to service pipeline/);
  assert.match(page, /overflow-x-hidden/);
  assert.match(page, /md:p-5/);
  assert.match(chrome, /aria-live="polite"/);
  assert.match(table, /ArrowDown/);
  assert.match(table, /Home/);
  assert.match(table, /End/);
  assert.match(table, /Enter/);
  assert.match(table, /overflow-x-auto/);
  assert.match(table, /scope="col"/);
  assert.match(table, /Filtering does not re-rank/);
});
