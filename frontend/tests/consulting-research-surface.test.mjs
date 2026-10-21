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

test("export gate also rejects free-text prohibited content as defense in depth", () => {
  const packet = buildSurfaceFixture();
  const adapted = adaptResearchSurface(packet);
  adapted.model.sections[0].rows[0].summary = "Leaked after adaptation: internal prompt details for this engagement.";
  const exported = buildClientSafeSurfaceExport(adapted.model);
  assert.equal(exported.accepted, false);
  assert.equal(exported.reason, "prohibited_value");
});

test("free-text mentions of prohibited topics are rejected at ingestion, not just key names", () => {
  const packet = buildSurfaceFixture();
  packet.sections[0].rows[0].summary = "Our internal formula is cost * 1.4, and this is shared with another_client too.";
  const adapted = adaptResearchSurface(packet);
  assert.equal(adapted.rejected, true);
  assert.equal(adapted.reason, "prohibited_field");
  assert.equal(adapted.model.availability, "unavailable");

  const crossWorkspace = buildSurfaceFixture();
  crossWorkspace.sections[1].rows[0].summary = "Copied from a different client's workspace for comparison.";
  assert.equal(adaptResearchSurface(crossWorkspace).rejected, true);
});

test("benign summaries mentioning 'client' without a cross-tenant qualifier are not rejected", () => {
  const packet = buildSurfaceFixture();
  packet.sections[0].rows[0].summary = "Client demand held steady quarter over quarter.";
  const adapted = adaptResearchSurface(packet);
  assert.equal(adapted.rejected, false);
  assert.equal(adapted.model.sections[0].rows[0].summary, "Client demand held steady quarter over quarter.");
});

test("keyboard stays in source order and source has no mutation client", async () => {
  const order = ["demand", "customer", "supplier"];
  assert.equal(moveSelection(order, "demand", "ArrowDown"), "customer");
  assert.equal(moveSelection(order, "supplier", "Home"), "demand");
  const source = await readFile(new URL("../src/features/consulting-research-surface/components/ConsultingResearchSurface.tsx", import.meta.url), "utf8");
  const page = await readFile(new URL("../src/features/consulting-research-surface/ConsultingResearchSurfacePage.tsx", import.meta.url), "utf8");
  const main = await readFile(new URL("../src/main.tsx", import.meta.url), "utf8");
  assert.match(source, /aria-live="polite"/);
  assert.match(source, /<table/);
  assert.match(source, /motion-reduce:transition-none/);
  assert.match(source, /overflow-x-auto/);
  assert.doesNotMatch(source, /method:\s*["']POST["']|fetch\(/);
  assert.doesNotMatch(page, /Shell|Sidebar/);
  assert.match(page, /type="file"/);
  assert.match(page, /Demo\/fixture — not live evidence/);
  assert.match(page, /Reset demo fixture/);
  assert.match(page, /Reset live request/);
  assert.match(page, /Request live report/);
  assert.doesNotMatch(page, /localStorage|sessionStorage|indexedDB/i);
  assert.doesNotMatch(page, /workspace_id|workspaceId/);
  assert.match(main, /path:\s*["']\/operator\/consulting-research["']/);
  assert.match(main, /ConsultingResearchSurfacePage/);
});

test("market-research-service-v1 maps into surface model without live or launch authority", async () => {
  const { mapMarketResearchReport } = await import("../src/features/consulting-research-surface/lib/mapMarketResearchReport.ts");
  const sampleText = await readFile(
    new URL("../src/features/consulting-research-surface/fixtures/market_research_report_sample.json", import.meta.url),
    "utf8",
  );
  const sample = JSON.parse(sampleText);
  const mapped = mapMarketResearchReport(sample);
  assert.equal(mapped.ok, true);
  if (!mapped.ok) return;
  assert.equal(mapped.packet.version, "consulting-research-surface-v1");
  assert.equal(mapped.packet.live_validated, false);
  assert.equal(mapped.packet.launch_authorized, false);
  assert.equal(mapped.packet.draft_only, true);
  const adapted = adaptResearchSurface(mapped.packet);
  assert.equal(adapted.rejected, false);
  assert.equal(adapted.model.launch_authorized, false);
  assert.equal(adapted.model.live_validated, false);
  assert.ok(adapted.model.sections.length >= 1);
  assert.ok(adapted.model.sections.every((section) => section.rows.every((row) => row.evidence_class !== "live_validated")));
  const view = viewOf(mapped.packet);
  assert.notEqual(view.state, "success");
  assert.equal(view.launchAuthorized, false);
});

test("local report ingest rejects invalid secret oversized and mismatched contracts without echoing payloads", async () => {
  const {
    ingestLocalResearchReportJson,
    localReportRejectionMessage,
    MAX_LOCAL_RESEARCH_REPORT_BYTES,
  } = await import("../src/features/consulting-research-surface/lib/loadLocalResearchReport.ts");

  const badJson = ingestLocalResearchReportJson("{not-json");
  assert.equal(badJson.ok, false);
  if (!badJson.ok) {
    assert.equal(badJson.reason, "invalid_json");
    assert.doesNotMatch(localReportRejectionMessage(badJson.reason), /\{not-json/);
  }

  const secret = ingestLocalResearchReportJson(JSON.stringify({
    version: "consulting-research-surface-v1",
    engagement_id: "e1",
    display_name: "leak sk-live-abcdefghijklmnopqrstuv",
    sections: [],
  }));
  assert.equal(secret.ok, false);
  if (!secret.ok) {
    assert.equal(secret.reason, "prohibited_or_secret_shaped");
    assert.doesNotMatch(localReportRejectionMessage(secret.reason), /sk-live-/);
  }

  const mismatch = ingestLocalResearchReportJson(JSON.stringify({ report_version: "other-v1", candidate_id: "x" }));
  assert.equal(mismatch.ok, false);
  if (!mismatch.ok) assert.equal(mismatch.reason, "unsupported_contract");

  const sampleText = await readFile(
    new URL("../src/features/consulting-research-surface/fixtures/market_research_report_sample.json", import.meta.url),
    "utf8",
  );
  const ok = ingestLocalResearchReportJson(sampleText);
  assert.equal(ok.ok, true);
  if (ok.ok) assert.equal(ok.source, "market-research-service-v1");

  const surfaceOk = ingestLocalResearchReportJson(JSON.stringify(buildSurfaceFixture()));
  assert.equal(surfaceOk.ok, true);
  if (surfaceOk.ok) assert.equal(surfaceOk.source, "consulting-research-surface-v1");

  assert.ok(MAX_LOCAL_RESEARCH_REPORT_BYTES <= 512 * 1024);
  const { loadLocalResearchReportFile } = await import("../src/features/consulting-research-surface/lib/loadLocalResearchReport.ts");
  const huge = {
    name: "huge.json",
    size: MAX_LOCAL_RESEARCH_REPORT_BYTES + 1,
    text: async () => sampleText,
  };
  const rejected = await loadLocalResearchReportFile(huge);
  assert.equal(rejected.ok, false);
  if (!rejected.ok) assert.equal(rejected.reason, "file_too_large");
});

test("loading and error states stay honest on the page contract", async () => {
  const loading = composeResearchSurface({
    loading: true,
    errorMessage: null,
    model: adaptResearchSurface(buildSurfaceFixture()).model,
    rejected: false,
    selectedSectionId: null,
  });
  assert.equal(loading.state, "loading");
  const errored = composeResearchSurface({
    loading: false,
    errorMessage: "Selected report was rejected. Payload not shown.",
    model: adaptResearchSurface(buildSurfaceFixture()).model,
    rejected: false,
    selectedSectionId: null,
  });
  assert.equal(errored.state, "error");
  assert.match(errored.message, /Payload not shown/);
});
