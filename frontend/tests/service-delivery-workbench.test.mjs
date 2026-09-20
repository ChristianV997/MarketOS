import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { adaptServiceProjection, neverUpgradeEvidenceClass, normalizeEvidenceClass, normalizeLifecycle } from "../src/features/service-delivery-workbench/lib/adaptServiceProjection.ts";
import { composeWorkbenchViewModel, moveSelection } from "../src/features/service-delivery-workbench/lib/composeWorkbenchViewModel.ts";
import { buildClientSafeServiceExport, containsSecretShapedValue, EXPORT_OMIT_KEYS } from "../src/features/service-delivery-workbench/lib/exportClientSafeEngagement.ts";
import { EMPTY_FILTERS, filterEngagements } from "../src/features/service-delivery-workbench/lib/filterEngagements.ts";
import { httpErrorUnavailableEnvelope } from "../src/features/service-delivery-workbench/lib/unservedGetEnvelope.ts";
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
    "intake", "screening", "data_inadequate", "eligible", "scoped", "evidence_collection",
    "analysis", "draft_ready", "client_review", "revision_requested",
    "approved", "delivered", "renewal_candidate", "upsell_candidate",
    "paused", "cancelled", "rejected", "unavailable",
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

test("adapter refuses to upgrade a weaker base evidence class", () => {
  const result = adaptServiceProjection({
    schema_version: "service-engagement-projection-v1",
    engagements: [{
      engagement_id: "eng-upgrade",
      service_id: "product-validation-sprint",
      lifecycle_state: "analysis",
      evidence: [{
        evidence_id: "e1",
        title: "claim",
        base_class: "fixture",
        evidence_class: "live_validated",
        summary: "must remain fixture",
      }],
    }],
  });
  assert.equal(result.projection.engagements[0].evidence[0].evidence_class, "fixture");
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
  assert.match(loading.pipelineEmptyCopy, /Loading the service-delivery workbench/);
  const empty = composeWorkbenchViewModel({
    isLoading: false, errorMessage: null, projection: null, filters: EMPTY_FILTERS, selectedId: null,
  });
  assert.equal(empty.surface, "empty");
  assert.match(empty.pipelineEmptyCopy, /No sanitized service-engagement projection/);
  const unavailable = composeWorkbenchViewModel({
    isLoading: false, errorMessage: "boom", projection: null, filters: EMPTY_FILTERS, selectedId: null,
  });
  assert.equal(unavailable.surface, "unavailable");
  assert.match(unavailable.pipelineEmptyCopy, /Demo fixtures are not substituted/);
  assert.doesNotMatch(unavailable.pipelineEmptyCopy, /Clear filters/);
});

test("unserved GET envelope keeps the pipeline copy unavailable instead of filter-empty", () => {
  const envelope = httpErrorUnavailableEnvelope(502, { error: "bad_gateway" });
  const adapted = adaptServiceProjection(envelope);
  assert.equal(adapted.rejected, false);
  const view = composeWorkbenchViewModel({
    isLoading: false,
    errorMessage: null,
    projection: adapted.projection,
    filters: EMPTY_FILTERS,
    selectedId: null,
  });
  assert.equal(view.surface, "unavailable");
  assert.equal(view.filtered.length, 0);
  assert.match(view.pipelineEmptyCopy, /Demo fixtures are not substituted/);
  assert.doesNotMatch(view.pipelineEmptyCopy, /Clear filters/);
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
  assert.match(page, /Skip to service pipeline/);
  assert.match(page, /not commercially validated/);
  assert.match(table, /Home/);
  assert.match(table, /End/);
  assert.match(workflow, /Package and scope review/);
  assert.match(workflow, /Client review \/ revision \/ approval \/ delivery/);
  assert.match(workflow, /Draft report preview/);
  assert.match(sidebar, /\/operator\/services/);
  assert.match(main, /\/operator\/services/);
});

test("scale fixture exists for one hundred engagements", () => {
  const scale = buildScaleProjection(100, 30, 15);
  assert.equal(scale.engagements.length, 100);
  assert.equal(scale.engagements[0].evidence.length, 30);
  assert.equal(scale.engagements[0].deliverables.length, 15);
});

test("fixture compose never reports success or live_validated", () => {
  const demo = buildDemoProjection();
  const view = composeWorkbenchViewModel({
    isLoading: false,
    errorMessage: null,
    projection: demo,
    filters: EMPTY_FILTERS,
    selectedId: demo.engagements[0].engagement_id,
  });
  assert.notEqual(view.surface, "success");
  assert.equal(view.liveEndpointUnavailable, true);
});

test("artifact-backed projection is available read-only without becoming live validation", () => {
  const source = buildDemoProjection();
  const result = adaptServiceProjection({
    ...source,
    live_endpoint_status: "available_read_only",
  });
  assert.equal(result.rejected, false);
  assert.equal(result.projection.live_endpoint_status, "available_read_only");
  const view = composeWorkbenchViewModel({
    isLoading: false,
    errorMessage: null,
    projection: result.projection,
    filters: EMPTY_FILTERS,
    selectedId: result.projection.engagements[0].engagement_id,
  });
  assert.notEqual(view.surface, "success");
  assert.equal(view.liveEndpointUnavailable, false);
  assert.match(view.statusMessage, /available_read_only/);
  assert.match(view.statusMessage, /Envelope:/);
  assert.notEqual(view.surface, "success");
  assert.notEqual(result.projection.engagements[0].evidence[0].evidence_class, "live_validated");
});

test("adapter maps a #261 plane-shaped engagement without recalculating economics", () => {
  const result = adaptServiceProjection({
    report_version: "service-delivery-plane-v1",
    generated_at: "2026-09-18T00:00:00Z",
    packages: [],
    engagements: [{
      engagement_id: "eng-plane-1",
      client_id: "client-a",
      workspace_id: "ws-a",
      package_id: "client_product_validation_sprint",
      scope: "Named SKU review only",
      lifecycle_state: "client_review",
      data_quality_state: "eligible",
      intake_data: { sku: "ABC-1" },
      evidence_set: [{ evidence_id: "e1", title: "fixture shot", evidence_class: "fixture", summary: "screening copy" }],
      deliverable_ids: ["pack-1"],
      fee: { amount: "1200.00", currency: "USD", evidence_class: "assumption" },
      contribution: null,
      assumptions: ["planning fee copy"],
      missing_information: [],
    }],
  });
  assert.equal(result.rejected, false);
  assert.equal(result.projection.input_contract, "service-delivery-plane-v1");
  assert.equal(result.projection.availability, "manual_import");
  assert.equal(result.projection.live_endpoint_status, "unavailable");
  assert.equal(result.projection.engagements[0].service_id, "product-validation-sprint");
  assert.equal(result.projection.engagements[0].lifecycle_state, "client_review");
  assert.equal(result.projection.engagements[0].economics.frontend_calculates, false);
  assert.equal(result.projection.engagements[0].economics.fee?.amount_label, "1200.00");
  assert.equal(result.projection.engagements[0].evidence[0].evidence_class, "fixture");
});

test("adapter rejects duplicate ids, missing ids, malformed artifacts, leakage, and secrets", () => {
  assert.equal(adaptServiceProjection({
    schema_version: "service-engagement-projection-v1",
    engagements: [
      { engagement_id: "dup", service_id: "product-validation-sprint" },
      { engagement_id: "dup", service_id: "launch-draft-pack" },
    ],
  }).rejection_reason?.startsWith("duplicate_engagement_id"), true);
  assert.equal(adaptServiceProjection({
    schema_version: "service-engagement-projection-v1",
    engagements: [{ service_id: "product-validation-sprint" }],
  }).rejection_reason, "missing_engagement_id");
  assert.equal(adaptServiceProjection(null).rejected, true);
  assert.match(String(adaptServiceProjection({
    schema_version: "service-engagement-projection-v1",
    engagements: [{
      engagement_id: "leak",
      service_id: "product-validation-sprint",
      cross_client_data: { other: "ws-b" },
    }],
  }).rejection_reason), /secret_or_cross_workspace|cross_workspace/);
  assert.equal(adaptServiceProjection({
    schema_version: "service-engagement-projection-v1",
    engagements: [{
      engagement_id: "sec",
      service_id: "product-validation-sprint",
      evidence: [{ title: "x", summary: "sk-live-abcdefghijklmnopqrstuvwxyz" }],
    }],
  }).rejected, true);
});

test("data_inadequate export lists exact missing client input", () => {
  const engagement = buildOneClientProjection().engagements[0];
  const exported = buildClientSafeServiceExport(engagement);
  assert.equal(exported.accepted, false);
  assert.match(String(exported.rejection_reason), /Missing client input/);
  assert.equal(Array.isArray(exported.payload?.required_from_client), true);
});

test("hook source uses #213 apiBase and never POSTs", async () => {
  const source = await readFile(new URL("../src/features/service-delivery-workbench/hooks/useServiceDeliveryWorkbench.ts", import.meta.url), "utf8");
  assert.match(source, /joinApiPath/);
  assert.match(source, /resolveApiBaseUrl/);
  assert.match(source, /adaptServiceProjection/);
  assert.doesNotMatch(source, /method: "POST"/);
  assert.doesNotMatch(source, /\.sort\(/);
});

test("adapter and filter sources never sort or recalculate contribution", async () => {
  const adapter = await readFile(new URL("../src/features/service-delivery-workbench/lib/adaptServiceProjection.ts", import.meta.url), "utf8");
  const filter = await readFile(new URL("../src/features/service-delivery-workbench/lib/filterEngagements.ts", import.meta.url), "utf8");
  assert.doesNotMatch(adapter, /\.sort\(/);
  assert.doesNotMatch(filter, /\.sort\(/);
  assert.match(adapter, /frontend_calculates: false/);
});

test("HTTP error JSON stays unavailable and is never fixture or empty success", () => {
  const envelope = httpErrorUnavailableEnvelope(500, { detail: "Internal Server Error" });
  const result = adaptServiceProjection(envelope, "live-get");
  assert.equal(result.rejected, false);
  assert.equal(result.projection.availability, "unavailable");
  assert.equal(result.projection.live_endpoint_status, "unavailable");
  assert.equal(result.projection.engagements.length, 0);
  const view = composeWorkbenchViewModel({
    isLoading: false,
    errorMessage: "Canonical GET unavailable (500).",
    projection: result.projection,
    filters: EMPTY_FILTERS,
    selectedId: null,
  });
  assert.equal(view.surface, "unavailable");
  assert.notEqual(view.surface, "empty");
  assert.notEqual(view.surface, "success");
  assert.match(view.statusMessage, /unavailable/i);
});

test("missing producer currency is labeled unavailable instead of inventing USD", () => {
  const demo = buildDemoProjection();
  const first = demo.engagements[0];
  const result = adaptServiceProjection({
    ...demo,
    engagements: [{
      ...first,
      economics: {
        ...first.economics,
        fee: { amount_label: "99.00" },
      },
    }],
  });
  assert.equal(result.projection.engagements[0].economics.fee.currency, "unavailable");
  assert.notEqual(result.projection.engagements[0].economics.fee.currency, "USD");
});

test("client-safe export rejects private notes, cross-client keys, and formula-shaped summaries", () => {
  assert.equal(containsSecretShapedValue({ private_note: "do not export" }), true);
  assert.equal(containsSecretShapedValue({ private_notes: "do not export" }), true);
  assert.equal(containsSecretShapedValue({ cross_client_data: "other-workspace" }), true);
  const engagement = buildDemoProjection().engagements.find((row) => !row.eligibility.data_inadequate)
    ?? buildDemoProjection().engagements[0];
  const formulaExport = buildClientSafeServiceExport({
    ...engagement,
    evidence: [{ title: "econ", evidence_class: "fixture", summary: "contribution = fee - labor" }],
  });
  assert.equal(formulaExport.accepted, false);
});
