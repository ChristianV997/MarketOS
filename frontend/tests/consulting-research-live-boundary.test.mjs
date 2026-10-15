/**
 * Integration-contract tests for the live research boundary.
 * Mocked fetch responses are NOT live validation.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { buildSurfaceFixture } from "../src/features/consulting-research-surface/fixtures/surfaceFixture.ts";
import {
  LIVE_RESEARCH_REPORT_ENDPOINT,
  LIVE_RESEARCH_REQUEST_VERSION,
  buildLiveResearchRequest,
  liveResearchBoundaryCopy,
} from "../src/features/consulting-research-surface/contracts/liveResearchReport.ts";
import {
  adaptLiveResearchResponse,
  observationsFromSurfaceModel,
} from "../src/features/consulting-research-surface/lib/adaptLiveResearchResponse.ts";
import {
  buildLiveResearchReportUrl,
  fetchLiveResearchReport,
} from "../src/features/consulting-research-surface/lib/liveResearchReportApi.ts";
import { adaptResearchSurface } from "../src/features/consulting-research-surface/lib/adaptResearchSurface.ts";
import { composeResearchSurface } from "../src/features/consulting-research-surface/lib/composeResearchSurface.ts";

function mockResponse(status, body) {
  const text = typeof body === "string" ? body : JSON.stringify(body);
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => text,
  };
}

test("live contract endpoint and request version are stable handoff constants", () => {
  assert.equal(LIVE_RESEARCH_REPORT_ENDPOINT, "/api/consulting-research/report");
  assert.equal(LIVE_RESEARCH_REQUEST_VERSION, "consulting-live-research-request-v1");
  const req = buildLiveResearchRequest({
    query: "portable blender",
    category: "kitchen",
    geography: "MX",
    language: "es",
    buyer_context: "price sensitive",
  });
  assert.equal(req.request_version, LIVE_RESEARCH_REQUEST_VERSION);
  assert.equal(req.query, "portable blender");
  assert.equal("workspace_id" in req, false);
  assert.match(buildLiveResearchReportUrl({ baseUrl: "http://example.test" }), /\/api\/consulting-research\/report$/);
});

test("without session provider live fetch stays auth_required and does not call network", async () => {
  let called = 0;
  const result = await fetchLiveResearchReport({
    request: buildLiveResearchRequest({ query: "x" }),
    session: null,
    fetchImpl: async () => {
      called += 1;
      return mockResponse(200, {});
    },
  });
  assert.equal(result.kind, "auth_required");
  if (result.kind === "auth_required") {
    assert.equal(result.reason, "session_provider_unavailable");
  }
  assert.equal(called, 0);
  assert.match(liveResearchBoundaryCopy("auth_required", "session_provider_unavailable").body, /not live evidence/i);
});

test("unauthorized unavailable forbidden and error transport kinds map safely", async () => {
  const session = { hasCookieSession: true };

  const unauthorized = await fetchLiveResearchReport({
    request: buildLiveResearchRequest({ query: "q" }),
    session,
    fetchImpl: async () => mockResponse(401, { detail: "nope" }),
  });
  assert.equal(unauthorized.kind, "unauthorized");

  const forbidden = await fetchLiveResearchReport({
    request: buildLiveResearchRequest({ query: "q" }),
    session,
    fetchImpl: async () => mockResponse(403, { detail: "nope" }),
  });
  assert.equal(forbidden.kind, "forbidden");

  const missing = await fetchLiveResearchReport({
    request: buildLiveResearchRequest({ query: "q" }),
    session,
    fetchImpl: async () => mockResponse(404, "missing"),
  });
  assert.equal(missing.kind, "unavailable");
  if (missing.kind === "unavailable") assert.equal(missing.reason, "endpoint_not_available");

  const identityDown = await fetchLiveResearchReport({
    request: buildLiveResearchRequest({ query: "q" }),
    session,
    fetchImpl: async () => mockResponse(503, { detail: "identity_provider_unavailable" }),
  });
  assert.equal(identityDown.kind, "unavailable");

  const serverError = await fetchLiveResearchReport({
    request: buildLiveResearchRequest({ query: "q" }),
    session,
    fetchImpl: async () => mockResponse(500, "boom"),
  });
  assert.equal(serverError.kind, "error");
});

test("client workspace authority on request is rejected before fetch", async () => {
  let called = 0;
  const result = await fetchLiveResearchReport({
    request: {
      ...buildLiveResearchRequest({ query: "q" }),
      workspace_id: "spoofed",
    },
    session: { hasCookieSession: true },
    fetchImpl: async () => {
      called += 1;
      return mockResponse(200, {});
    },
  });
  assert.equal(result.kind, "error");
  if (result.kind === "error") assert.equal(result.reason, "client_workspace_authority_rejected");
  assert.equal(called, 0);
});

test("mocked successful server MRS packet adapts without fixture live promotion", async () => {
  const sampleText = await readFile(
    new URL("../src/features/consulting-research-surface/fixtures/market_research_report_sample.json", import.meta.url),
    "utf8",
  );
  const sample = JSON.parse(sampleText);
  const session = {
    getAccessToken: async () => "test-token-not-stored",
  };
  let sawAuth = false;
  let sawCredentials = null;
  const result = await fetchLiveResearchReport({
    request: buildLiveResearchRequest({ query: "portable blender", geography: "MX" }),
    session,
    fetchImpl: async (_url, init) => {
      sawAuth = String(init?.headers?.Authorization || "").startsWith("Bearer ");
      sawCredentials = init?.credentials;
      assert.equal(init?.method, "POST");
      const body = JSON.parse(String(init?.body || "{}"));
      assert.equal(body.workspace_id, undefined);
      return mockResponse(200, sample);
    },
  });
  assert.equal(result.kind, "ok");
  assert.equal(sawAuth, true);
  assert.equal(sawCredentials, "same-origin");
  if (result.kind !== "ok") return;

  const adapted = adaptLiveResearchResponse(result.payload);
  assert.equal(adapted.ok, true);
  if (!adapted.ok) return;
  assert.ok(["observed", "partial", "stale", "mixed"].includes(adapted.evidenceLabel));
  assert.notEqual(adapted.evidenceLabel, "server");
  assert.equal(adapted.model.live_validated, false);
  assert.equal(adapted.model.launch_authorized, false);
  assert.equal(adapted.model.draft_only, true);
  assert.ok(adapted.sources.length >= 1);
  const view = composeResearchSurface({
    loading: false,
    errorMessage: null,
    model: adapted.model,
    rejected: false,
    selectedSectionId: null,
  });
  assert.notEqual(view.state, "success");
  assert.ok(["blocked", "stale", "partial", "empty", "unavailable"].includes(view.state));
});

test("fixture availability is rejected on live transport adapter", () => {
  const fixture = buildSurfaceFixture();
  const adapted = adaptLiveResearchResponse(fixture);
  assert.equal(adapted.ok, false);
  if (!adapted.ok) assert.equal(adapted.reason, "fixture_packet_rejected_on_live_transport");
});

test("partial and stale observations preserve every row and never invent collected", () => {
  const packet = buildSurfaceFixture();
  packet.availability = "partial";
  packet.blockers = [];
  for (const section of packet.sections) {
    for (const row of section.rows) {
      row.evidence_class = section.section_id === "competitor" ? "observed" : "derived";
      row.fresh = section.section_id === "competitor" ? false : true;
      row.conflict_note = section.section_id === "demand" ? "Counts disagree." : null;
    }
    // second row on demand — must not be dropped
    if (section.section_id === "demand") {
      section.rows.push({
        evidence_id: "demand-2",
        title: "second demand row",
        evidence_class: "assumed",
        summary: "Assumed demand band.",
        source_label: "planner",
        captured_at: "2026-01-01",
        fresh: true,
        conflict_note: null,
      });
    }
  }
  const model = adaptResearchSurface(packet).model;
  const observed = observationsFromSurfaceModel(model);
  assert.equal(observed.ok, true);
  if (!observed.ok) return;
  const sources = observed.sources;
  assert.ok(sources.length >= 7, `expected every row, got ${sources.length}`);
  assert.ok(sources.some((row) => row.source_id.includes("demand-2") && row.status === "partial"));
  assert.ok(sources.some((row) => row.status === "stale"));
  assert.ok(sources.every((row) => row.status !== "collected" || !row.source_id.startsWith("demand:")));
  assert.equal(sources.filter((row) => row.source_id.startsWith("demand:")).length, 2);
});

test("page source keeps demo opt-in and forbids storage or workspace rebinding", async () => {
  const page = await readFile(
    new URL("../src/features/consulting-research-surface/ConsultingResearchSurfacePage.tsx", import.meta.url),
    "utf8",
  );
  const api = await readFile(
    new URL("../src/features/consulting-research-surface/lib/liveResearchReportApi.ts", import.meta.url),
    "utf8",
  );
  assert.match(page, /Enable demo\/fixture path/);
  assert.match(page, /never fall back here automatically|Do NOT load fixture on failure|no fixture fallback/i);
  assert.doesNotMatch(page, /localStorage\.|sessionStorage\.|indexedDB/i);
  assert.doesNotMatch(api, /localStorage\.|sessionStorage\.|indexedDB/i);
  assert.match(api, /credentials:\s*["']same-origin["']/);
  assert.match(api, /client_workspace_authority_rejected/);
  assert.doesNotMatch(page, /\bApprove\b|\bSpend\b|\bPublish\b|Launch authorized/);
});
