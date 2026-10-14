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
  assert.ok(["server", "partial", "stale"].includes(adapted.evidenceLabel));
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

test("partial and stale observations stay labeled from surface model", () => {
  const packet = buildSurfaceFixture();
  packet.availability = "partial";
  packet.blockers = [];
  packet.sections[2].rows[0].fresh = false;
  const model = adaptResearchSurface(packet).model;
  const sources = observationsFromSurfaceModel(model);
  assert.ok(sources.some((row) => row.status === "stale"));
  assert.ok(sources.some((row) => row.source_id === "supplier" && row.status === "partial"));
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
