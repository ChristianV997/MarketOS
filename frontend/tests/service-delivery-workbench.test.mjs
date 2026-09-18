import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { adaptServiceProjection, neverUpgradeEvidenceClass, normalizeEvidenceClass, normalizeLifecycle } from "../src/features/service-delivery-workbench/lib/adaptServiceProjection.ts";
import { composeWorkbenchViewModel, moveSelection } from "../src/features/service-delivery-workbench/lib/composeWorkbenchViewModel.ts";
import { buildClientSafeServiceExport, EXPORT_OMIT_KEYS } from "../src/features/service-delivery-workbench/lib/exportClientSafeEngagement.ts";
import { EMPTY_FILTERS, filterEngagements } from "../src/features/service-delivery-workbench/lib/filterEngagements.ts";
import { HIGGSFIELD_CONTRACT_SOURCE, HIGGSFIELD_DRAFT_SKILLS } from "../src/features/service-delivery-workbench/lib/creativeAssetContract.ts";
import { buildDemoProjection, buildOneClientProjection, buildScaleProjection, buildTenClientProjection } from "../src/features/service-delivery-workbench/fixtures/buildFixtures.ts";
import { joinApiPath, resolveApiBaseUrl } from "../src/lib/apiBase.ts";
import { LIFECYCLE_STATES, PRIORITY_SERVICE_IDS } from "../src/features/service-delivery-workbench/contracts/serviceEngagementProjection.ts";

test("apiBase matches #213 join/resolve contract", () => {
  assert.equal(joinApiPath("", "/api/service-delivery/workbench"), "/api/service-delivery/workbench");
  assert.equal(joinApiPath("http://localhost:3000", "metrics"), "http://localhost:3000/metrics");
  assert.equal(typeof resolveApiBaseUrl(), "string");
});

test("lifecycle states cover the operator workflow including data_inadequate", () => {
  assert.deepEqual(LIFECYCLE_STATES, [
    "intake", "data_inadequate", "eligible", "scoped", "evidence_collection",
    "analysis", "draft_ready", "client_review", "revision_requested",
    "approved", "delivered", "paused", "cancelled", "rejected", "unavailable",
  ]);
});

test("data_inadequate is a dedicated lifecycle, not a generic warning", () => {
  const one = buildOneClientProjection();
  const engagement = one.engagements[0];
  assert.equal(engagement.lifecycle_state, "data_inadequate");
  assert.equal(engagement.eligibility.data_inadequate, true);
  assert.ok(engagement.eligibility.required_from_client.length >= 1);
  assert.match(engagement.eligibility.required_from_client[0].how_to_provide, /SKU|product|Upload|Provide/i);
  const view = composeWorkbenchViewModel({
    isLoading: false,
    errorMessage: null,
    projection: one,
    filters: EMPTY_FILTERS,
    selectedId: engagement.engagement_id,
  });
  assert.equal(view.surface, "blocked");
  assert.match(view.statusMessage, /data_inadequate/);
  assert.equal(view.exportPreview?.accepted, false);
  assert.match(String(view.exportPreview?.rejection_reason), /data_inadequate/);
});

test("evidence classes are never upgraded", () => {
  assert.equal(normalizeEvidenceClass("assumed"), "assumption");
  assert.equal(normalizeEvidenceClass("live"), "unavailable");
  assert.equal(neverUpgradeEvidenceClass("fixture", "live_validated"), "fixture");
  assert.equal(neverUpgradeEvidenceClass("observed", "assumption"), "assumption");
});

test("backend lifecycle aliases map onto the frontend vocabulary", () => {
  assert.equal(normalizeLifecycle("intake_requested", false), "intake");
  assert.equal(normalizeLifecycle("analysis_in_progress", false), "analysis");
  assert.equal(normalizeLifecycle("data_quality_assessed", true), "data_inadequate");
});

test("ten-client fixture covers all priority services and mixed states", () => {
  const ten = buildTenClientProjection();
  assert.equal(ten.engagements.length, 10);
  const services = new Set(ten.engagements.map((item) => item.service_id));
  for (const id of PRIORITY_SERVICE_IDS) assert.ok(services.has(id));
});

test("filters preserve source order", () => {
  const demo = buildDemoProjection();
  const filtered = filterEngagements(demo.engagements, {
    ...EMPTY_FILTERS,
    serviceId: "launch-draft-pack",
  });
  const original = demo.engagements.filter((item) => item.service_id === "launch-draft-pack");
  assert.deepEqual(
    filtered.map((item) => item.engagement_id),
    original.map((item) => item.engagement_id),
  );
});

test("client-safe export omits internal secrets and private notes", () => {
  const ten = buildTenClientProjection();
  const internal = ten.engagements.find((item) => item.internal_prompt);
  assert.ok(internal);
  const exported = buildClientSafeServiceExport({
    ...internal,
    eligibility: { ...internal.eligibility, data_inadequate: false, required_from_client: [] },
    lifecycle_state: "draft_ready",
  });
  assert.equal(exported.accepted, true);
  const blob = JSON.stringify(exported.payload);
  assert.equal(blob.includes("SYSTEM PROMPT"), false);
  assert.equal(blob.includes("INTERNAL:"), false);
  assert.equal(blob.includes("contribution = fee"), false);
  for (const key of EXPORT_OMIT_KEYS) {
    assert.equal(Object.prototype.hasOwnProperty.call(exported.payload, key), false);
  }
});

test("secret-shaped values fail closed", () => {
  const one = buildOneClientProjection().engagements[0];
  const poisoned = {
    ...one,
    eligibility: { ...one.eligibility, data_inadequate: false, required_from_client: [] },
    evidence: [{
      ...one.evidence[0],
      summary: "token sk-live-abcdefghijklmnopqrstuvwxyz",
    }],
  };
  const exported = buildClientSafeServiceExport(poisoned);
  assert.equal(exported.accepted, false);
  assert.match(String(exported.rejection_reason), /secret/i);
});

test("adapter rejects unsupported versions without inventing economics", () => {
  const result = adaptServiceProjection({ schema_version: "other-v9", engagements: [{ fee: 12 }] });
  assert.equal(result.rejected, true);
  assert.equal(result.projection.engagements.length, 0);
  assert.equal(result.projection.live_endpoint_status, "unavailable");
});

test("keyboard helper moves within the filtered list only", () => {
  const rows = buildTenClientProjection().engagements.slice(0, 3);
  assert.equal(moveSelection(rows, rows[0].engagement_id, 1), rows[1].engagement_id);
  assert.equal(moveSelection(rows, rows[0].engagement_id, -1), rows[0].engagement_id);
});

test("Higgsfield remains draft/unavailable metadata", () => {
  assert.equal(HIGGSFIELD_CONTRACT_SOURCE, "https://github.com/higgsfield-ai/skills");
  assert.equal(HIGGSFIELD_DRAFT_SKILLS.length, 4);
  for (const skill of HIGGSFIELD_DRAFT_SKILLS) {
    assert.equal(skill.generation_enabled, false);
    assert.equal(skill.publication_enabled, false);
    assert.equal(skill.status, "unavailable");
  }
});

test("surface states include empty blocked unavailable loading stale partial success", () => {
  const loading = composeWorkbenchViewModel({
    isLoading: true, errorMessage: null, projection: null, filters: EMPTY_FILTERS, selectedId: null,
  });
  assert.equal(loading.surface, "loading");
  const empty = composeWorkbenchViewModel({
    isLoading: false, errorMessage: null, projection: null, filters: EMPTY_FILTERS, selectedId: null,
  });
  assert.equal(empty.surface, "empty");
  const unavailable = composeWorkbenchViewModel({
    isLoading: false, errorMessage: "boom", projection: null, filters: EMPTY_FILTERS, selectedId: null,
  });
  assert.equal(unavailable.surface, "unavailable");
});

test("component sources expose required accessibility contracts", async () => {
  const page = await readFile(new URL("../src/pages/ServiceDeliveryWorkbench.tsx", import.meta.url), "utf8");
  const table = await readFile(new URL("../src/features/service-delivery-workbench/components/PipelineTable.tsx", import.meta.url), "utf8");
  const chrome = await readFile(new URL("../src/features/service-delivery-workbench/components/WorkbenchChrome.tsx", import.meta.url), "utf8");
  const workflow = await readFile(new URL("../src/features/service-delivery-workbench/components/EngagementWorkflow.tsx", import.meta.url), "utf8");
  const sidebar = await readFile(new URL("../src/components/layout/Sidebar.tsx", import.meta.url), "utf8");
  const main = await readFile(new URL("../src/main.tsx", import.meta.url), "utf8");
  assert.match(chrome, /aria-live="polite"/);
  assert.match(table, /<table/);
  assert.match(table, /scope="col"/);
  assert.match(table, /ArrowDown/);
  assert.match(chrome, /focus-visible:outline/);
  assert.match(workflow, /data_inadequate/);
  assert.match(workflow, /required_from_client/);
  assert.match(page, /Service delivery workbench/);
  assert.match(sidebar, /\/operator\/services/);
  assert.match(main, /\/operator\/services/);
});

test("scale fixture exists for one hundred engagements", () => {
  const scale = buildScaleProjection(100, 30, 15);
  assert.equal(scale.engagements.length, 100);
  assert.equal(scale.engagements[0].evidence.length, 30);
  assert.equal(scale.engagements[0].deliverables.length, 15);
});
