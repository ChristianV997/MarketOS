/**
 * Adversarial integrity tests for the live research response adapter.
 * Mocked payloads are integration-contract evidence, not live validation.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { RESEARCH_SURFACE_VERSION, SECTION_IDS } from "../src/features/consulting-research-surface/contracts/researchSurface.ts";
import { buildSurfaceFixture } from "../src/features/consulting-research-surface/fixtures/surfaceFixture.ts";
import {
  adaptLiveResearchResponse,
  mapRecognizedEvidenceStatus,
  observationsFromSurfaceModel,
} from "../src/features/consulting-research-surface/lib/adaptLiveResearchResponse.ts";

function basePacket(overrides = {}) {
  const packet = buildSurfaceFixture();
  packet.availability = "partial";
  packet.blockers = [];
  for (const section of packet.sections) {
    section.missing = [];
    section.rows = [{
      evidence_id: `${section.section_id}-1`,
      title: `${section.section_id} note`,
      evidence_class: "observed",
      summary: "Observed copy.",
      source_label: "unit-test",
      captured_at: "2026-10-01T00:00:00Z",
      fresh: true,
      conflict_note: null,
    }];
  }
  return { ...packet, ...overrides };
}

test("mapRecognizedEvidenceStatus never defaults unknown or empty to collected", () => {
  assert.equal(mapRecognizedEvidenceStatus("observed", true, null), "collected");
  assert.equal(mapRecognizedEvidenceStatus("observed", false, null), "stale");
  assert.equal(mapRecognizedEvidenceStatus("observed", true, "conflict"), "partial");
  assert.equal(mapRecognizedEvidenceStatus("derived", true, null), "partial");
  assert.equal(mapRecognizedEvidenceStatus("assumed", true, null), "partial");
  assert.equal(mapRecognizedEvidenceStatus("manual", true, null), "partial");
  assert.equal(mapRecognizedEvidenceStatus("fixture", true, null), "partial");
  assert.equal(mapRecognizedEvidenceStatus("unavailable", true, null), "unavailable");
  assert.equal(mapRecognizedEvidenceStatus("totally_unknown", true, null), null);
  assert.equal(mapRecognizedEvidenceStatus("", true, null), null);
  assert.equal(mapRecognizedEvidenceStatus(null, true, null), null);
  assert.equal(mapRecognizedEvidenceStatus(undefined, true, null), null);
});

test("multiple rows per section are all preserved", () => {
  const packet = basePacket();
  const demand = packet.sections.find((section) => section.section_id === "demand");
  demand.rows.push({
    evidence_id: "demand-extra",
    title: "extra",
    evidence_class: "derived",
    summary: "Second row.",
    source_label: "unit-test",
    captured_at: null,
    fresh: null,
    conflict_note: null,
  });
  const adapted = adaptLiveResearchResponse(packet);
  assert.equal(adapted.ok, true);
  if (!adapted.ok) return;
  const demandRows = adapted.sources.filter((row) => row.source_id.startsWith("demand:"));
  assert.equal(demandRows.length, 2);
  assert.equal(adapted.sources.length, SECTION_IDS.length + 1);
  assert.equal(adapted.evidenceLabel, "mixed");
});

test("mixed stale conflict unavailable assumed derived stay distinct", () => {
  const packet = basePacket();
  const byId = Object.fromEntries(packet.sections.map((section) => [section.section_id, section]));
  byId.demand.rows[0].evidence_class = "observed";
  byId.demand.rows[0].conflict_note = "Conflict A";
  byId.customer.rows[0].evidence_class = "unavailable";
  byId.competitor.rows[0].evidence_class = "observed";
  byId.competitor.rows[0].fresh = false;
  byId.supplier.rows[0].evidence_class = "assumed";
  byId.logistics.rows[0].evidence_class = "derived";
  byId.economics.rows[0].evidence_class = "manual";

  const adapted = adaptLiveResearchResponse(packet);
  assert.equal(adapted.ok, true);
  if (!adapted.ok) return;
  const byPrefix = Object.fromEntries(
    adapted.sources.map((row) => [row.source_id.split(":")[0], row.status]),
  );
  assert.equal(byPrefix.demand, "partial");
  assert.equal(byPrefix.customer, "unavailable");
  assert.equal(byPrefix.competitor, "stale");
  assert.equal(byPrefix.supplier, "partial");
  assert.equal(byPrefix.logistics, "partial");
  assert.equal(byPrefix.economics, "partial");
  assert.equal(adapted.evidenceLabel, "mixed");
  assert.ok(!adapted.sources.every((row) => row.status === "collected"));
});

test("unknown evidence class rejects the live response before normalize can hide it", () => {
  const packet = basePacket();
  packet.sections[0].rows[0].evidence_class = "verified_live_magic";
  const adapted = adaptLiveResearchResponse(packet);
  assert.equal(adapted.ok, false);
  if (!adapted.ok) assert.equal(adapted.reason, "unrecognized_evidence_class");
});

test("live_validated claims on rows are rejected on live transport", () => {
  const packet = basePacket();
  packet.sections[0].rows[0].evidence_class = "live_validated";
  const adapted = adaptLiveResearchResponse(packet);
  assert.equal(adapted.ok, false);
  if (!adapted.ok) assert.equal(adapted.reason, "live_claim_rejected_on_live_transport");
});

test("missing evidence class rejects the live response", () => {
  const model = {
    version: RESEARCH_SURFACE_VERSION,
    engagement_id: "e",
    display_name: "n",
    offering_kind: "goods",
    availability: "partial",
    blockers: [],
    limitations: [],
    next_action: "review",
    next_action_executes: false,
    draft_only: true,
    live_validated: false,
    launch_authorized: false,
    sections: [{
      section_id: "demand",
      title: "demand",
      missing: [],
      rows: [{
        evidence_id: "d1",
        title: "t",
        evidence_class: null,
        summary: "s",
        source_label: null,
        captured_at: null,
        fresh: null,
        conflict_note: null,
      }],
    }],
  };
  const observed = observationsFromSurfaceModel(model);
  assert.equal(observed.ok, false);
  if (!observed.ok) assert.equal(observed.reason, "missing_evidence_class");
});

test("fixture rows on live transport are rejected even when availability is partial", () => {
  const packet = basePacket();
  packet.sections[1].rows[0].evidence_class = "fixture";
  const adapted = adaptLiveResearchResponse(packet);
  assert.equal(adapted.ok, false);
  if (!adapted.ok) assert.equal(adapted.reason, "fixture_row_rejected_on_live_transport");
});

test("malformed payloads fail closed without authority", () => {
  assert.equal(adaptLiveResearchResponse(null).ok, false);
  assert.equal(adaptLiveResearchResponse("not-json-object").ok, false);
  assert.equal(adaptLiveResearchResponse(42).ok, false);
  assert.equal(adaptLiveResearchResponse({ version: "nope" }).ok, false);
  const bad = adaptLiveResearchResponse({ hello: true });
  assert.equal(bad.ok, false);
  if (!bad.ok) assert.doesNotMatch(bad.reason, /hello/);
});

test("all-observed packet labels observed not server and keeps authority false", () => {
  const packet = basePacket();
  const adapted = adaptLiveResearchResponse(packet);
  assert.equal(adapted.ok, true);
  if (!adapted.ok) return;
  assert.equal(adapted.evidenceLabel, "observed");
  assert.ok(adapted.sources.every((row) => row.status === "collected"));
  assert.equal(adapted.model.live_validated, false);
  assert.equal(adapted.model.launch_authorized, false);
  assert.equal(adapted.model.draft_only, true);
});

test("empty section with missing fields becomes missing status, not collected", () => {
  const packet = basePacket();
  const supplier = packet.sections.find((section) => section.section_id === "supplier");
  supplier.rows = [];
  supplier.missing = ["supplier_legal_name"];
  const adapted = adaptLiveResearchResponse(packet);
  assert.equal(adapted.ok, true);
  if (!adapted.ok) return;
  const row = adapted.sources.find((item) => item.source_id.startsWith("supplier:"));
  assert.ok(row);
  assert.equal(row.status, "missing");
  assert.equal(adapted.evidenceLabel, "mixed");
});
