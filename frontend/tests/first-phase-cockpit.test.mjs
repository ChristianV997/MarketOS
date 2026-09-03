import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const featureRoot = new URL("../src/features/first-phase-cockpit/", import.meta.url);

const SCHEMA_V1 = "phase1-evidence-cockpit-v1";
const WINDOW_SIZE = 50;

function normalizeEvidenceMode(value) {
  if (!value) return "unknown";
  const lowered = String(value).toLowerCase();
  if (lowered.includes("fixture")) return "fixture_only";
  if (lowered.includes("manual")) return "manual";
  if (lowered.includes("simul")) return "simulated";
  if (lowered.includes("live")) return "live_readonly";
  return "unknown";
}

function deriveState(input) {
  if (input.isLoading) return "loading";
  const hasAnyData = Boolean(
    input.phase1Readiness || input.benchmark || input.publicMarket || input.researchPortfolio,
  );
  if (!hasAnyData) {
    if (input.readinessError && input.benchmarkError) return "unavailable";
    return "empty";
  }
  if (input.phase1Readiness?.overall_status === "blocked") return "blocked";
  if (input.phase1Readiness?.overall_status === "degraded") return "stale";
  const partialEndpoint =
    input.readinessError || input.benchmarkError || input.publicMarketError || input.researchError;
  if (partialEndpoint || input.phase1Readiness?.overall_status === "partially_ready") return "partial";
  return "success";
}

function mapCandidates(benchmark, evidenceMode) {
  if (!benchmark?.candidates?.length) return [];
  return benchmark.candidates.map((item, rankIndex) => ({
    candidateId: item.candidate.candidate_id,
    title: item.candidate.title,
    rankIndex,
    evidenceCompleteness: item.evidence_completeness ?? null,
    riskLevel: item.risk_level ?? null,
    commercialDecision: item.commercial_decision ?? null,
    evidenceMode,
    isTopCandidate: item.candidate.candidate_id === benchmark.top_candidate_id,
  }));
}

function filterCandidates(candidates, filter) {
  const query = filter.query.trim().toLowerCase();
  const filtered = [];
  for (const candidate of candidates) {
    if (filter.topOnly && !candidate.isTopCandidate) continue;
    if (filter.risk !== "all") {
      const risk = (candidate.riskLevel ?? "unknown").toLowerCase();
      if (risk !== filter.risk) continue;
    }
    if (filter.decision !== "all" && (candidate.commercialDecision ?? "") !== filter.decision) continue;
    if (query) {
      const haystack = [candidate.candidateId, candidate.title, candidate.commercialDecision]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      if (!haystack.includes(query)) continue;
    }
    filtered.push(candidate);
  }
  return filtered;
}

function windowCandidates(candidates, windowStart, windowSize = WINDOW_SIZE) {
  const size = Math.max(1, windowSize);
  const start = candidates.length === 0 ? 0 : Math.min(Math.max(0, windowStart), Math.max(0, candidates.length - size));
  return {
    visible: candidates.slice(start, start + size),
    windowStart: start,
    windowSize: size,
    total: candidates.length,
    hasMoreBefore: start > 0,
    hasMoreAfter: start + size < candidates.length,
  };
}

function formatFreshnessLabel(generatedAt, nowMs) {
  if (!generatedAt) return null;
  const parsed = Date.parse(generatedAt);
  if (Number.isNaN(parsed)) return "freshness_unavailable";
  const ageMinutes = Math.floor(Math.max(0, nowMs - parsed) / 60_000);
  if (ageMinutes < 1) return "fresh_<1m";
  if (ageMinutes < 60) return `age_${ageMinutes}m`;
  const ageHours = Math.floor(ageMinutes / 60);
  if (ageHours < 48) return `age_${ageHours}h`;
  return `age_${Math.floor(ageHours / 24)}d`;
}

function isStaleFreshness(label, staleAfterHours = 24) {
  if (!label || label === "freshness_unavailable") return false;
  if (label.endsWith("d")) {
    const days = Number(label.slice(4, -1));
    return Number.isFinite(days) && days * 24 >= staleAfterHours;
  }
  if (label.endsWith("h")) {
    const hours = Number(label.slice(4, -1));
    return Number.isFinite(hours) && hours >= staleAfterHours;
  }
  return false;
}

const SECRET_SHAPED = /sk-live-|sk-test-|ghp_|github_pat_|AKIA[0-9A-Z]{16}|bearer\s+[a-z0-9._-]{10,}/i;

function containsSecretShapedValue(value) {
  if (typeof value === "string") return SECRET_SHAPED.test(value);
  if (Array.isArray(value)) return value.some(containsSecretShapedValue);
  if (value && typeof value === "object") {
    return Object.entries(value).some(([key, item]) => {
      const keyL = key.toLowerCase().replace(/-/g, "_");
      if (keyL.includes("password") || keyL.includes("secret") || keyL.includes("api_key")) return true;
      return containsSecretShapedValue(item);
    });
  }
  return false;
}

function buildClientSafeExport(packet, exportedAt) {
  const payload = {
    export_version: "first-phase-cockpit-client-safe-v1",
    schema_version: packet.schemaVersion ?? "composed-live",
    exported_at: exportedAt,
    read_only: true,
    mutated: false,
    network_calls: false,
    state: packet.state,
    ranked_candidates: packet.rankedCandidates.map((c) => ({
      candidate_id: c.candidateId,
      title: c.title,
      rank_index: c.rankIndex,
      is_top_candidate: c.isTopCandidate,
    })),
    warnings: [...packet.warnings],
  };
  if (containsSecretShapedValue(payload)) {
    throw new Error("client_safe_export_rejected_secret_shaped_value");
  }
  return payload;
}

const PILLAR_IDS = new Set([
  "market_evidence",
  "consumer_attention",
  "supplier_feasibility",
  "economics",
  "provenance",
  "freshness",
]);

const SUPPORTED_SCHEMAS = new Set([SCHEMA_V1]);

function validateEvidenceCockpitApiPacket(raw) {
  if (!raw || typeof raw !== "object") return { ok: false, reason: "packet_not_object" };
  if (raw.read_only !== true) return { ok: false, reason: "read_only_required" };
  if (raw.mutated !== false) return { ok: false, reason: "mutated_must_be_false" };
  if (typeof raw.schema_version !== "string" || !raw.schema_version) {
    return { ok: false, reason: "schema_version_required" };
  }
  if (!SUPPORTED_SCHEMAS.has(raw.schema_version)) {
    return { ok: false, reason: "schema_version_unsupported" };
  }
  if (typeof raw.report_version !== "string" || !raw.report_version) {
    return { ok: false, reason: "report_version_required" };
  }
  if (typeof raw.generated_at !== "string" || !raw.generated_at) {
    return { ok: false, reason: "generated_at_required" };
  }
  if (!Array.isArray(raw.ranked_candidates)) return { ok: false, reason: "ranked_candidates_required" };
  if (!Array.isArray(raw.pillars)) return { ok: false, reason: "pillars_required" };
  let previousRank = -1;
  for (const candidate of raw.ranked_candidates) {
    if (!candidate || typeof candidate !== "object") return { ok: false, reason: "candidate_malformed" };
    if (typeof candidate.candidate_id !== "string" || typeof candidate.title !== "string") {
      return { ok: false, reason: "candidate_identity_required" };
    }
    if (typeof candidate.rank_index !== "number" || !Number.isInteger(candidate.rank_index) || candidate.rank_index < 0) {
      return { ok: false, reason: "candidate_rank_index_invalid" };
    }
    if (candidate.rank_index < previousRank) return { ok: false, reason: "candidate_rank_index_out_of_order" };
    previousRank = candidate.rank_index;
  }
  for (const pillar of raw.pillars) {
    if (!pillar || typeof pillar !== "object") return { ok: false, reason: "pillar_malformed" };
    if (!PILLAR_IDS.has(pillar.pillar_id)) return { ok: false, reason: "pillar_id_invalid" };
  }
  for (const key of ["trustos", "governor", "approval_ledger"]) {
    if (!raw[key] || typeof raw[key] !== "object") return { ok: false, reason: `${key}_required` };
  }
  if (!raw.fingerprint || typeof raw.fingerprint !== "object") return { ok: false, reason: "fingerprint_required" };
  if (containsSecretShapedValue(raw)) return { ok: false, reason: "secret_shaped_value_rejected" };
  return { ok: true, packet: raw };
}

function normalizeRenderModel(packet) {
  return {
    state: packet.state,
    evidence_mode: packet.fingerprint.evidenceMode,
    candidate_ids_in_order: packet.rankedCandidates.map((c) => c.candidateId),
    candidate_count: packet.rankedCandidates.length,
    control_plane_statuses: Object.fromEntries(packet.controlPlanes.map((s) => [s.id, s.status])),
    schema_version: packet.fingerprint.schemaVersion,
    read_only: packet.fingerprint.readOnly,
  };
}

function buildLargeCandidates(count) {
  return Array.from({ length: count }, (_, rankIndex) => ({
    candidateId: `cand-${String(rankIndex).padStart(4, "0")}`,
    title: `Candidate ${rankIndex}`,
    rankIndex,
    riskLevel: rankIndex % 3 === 0 ? "high" : rankIndex % 3 === 1 ? "medium" : "low",
    commercialDecision: rankIndex % 2 === 0 ? "hold_for_credentials" : "reject_insufficient_evidence",
    isTopCandidate: rankIndex === 0,
  }));
}

const SAMPLE_CANDIDATES = [
  {
    candidateId: "alpha",
    title: "Alpha Widget",
    rankIndex: 0,
    riskLevel: "high",
    commercialDecision: "reject_insufficient_evidence",
    isTopCandidate: false,
  },
  {
    candidateId: "beta",
    title: "Beta Gadget",
    rankIndex: 1,
    riskLevel: "medium",
    commercialDecision: "hold_for_credentials",
    isTopCandidate: true,
  },
  {
    candidateId: "gamma",
    title: "Gamma Tool",
    rankIndex: 2,
    riskLevel: "low",
    commercialDecision: "hold_for_credentials",
    isTopCandidate: false,
  },
];

test("state transitions cover loading empty blocked unavailable stale partial success", () => {
  assert.equal(deriveState({ isLoading: true }), "loading");
  assert.equal(
    deriveState({
      isLoading: false,
      phase1Readiness: null,
      benchmark: null,
      publicMarket: null,
      researchPortfolio: null,
      readinessError: false,
      benchmarkError: false,
    }),
    "empty",
  );
  assert.equal(
    deriveState({
      isLoading: false,
      phase1Readiness: null,
      benchmark: null,
      publicMarket: null,
      researchPortfolio: null,
      readinessError: true,
      benchmarkError: true,
    }),
    "unavailable",
  );
  assert.equal(
    deriveState({
      isLoading: false,
      phase1Readiness: { overall_status: "blocked" },
      benchmark: { candidates: [] },
      publicMarket: null,
      researchPortfolio: null,
    }),
    "blocked",
  );
  assert.equal(
    deriveState({
      isLoading: false,
      phase1Readiness: { overall_status: "degraded" },
      benchmark: { candidates: [{}] },
      publicMarket: null,
      researchPortfolio: null,
    }),
    "stale",
  );
  assert.equal(
    deriveState({
      isLoading: false,
      phase1Readiness: { overall_status: "partially_ready" },
      benchmark: { candidates: [{}] },
      publicMarket: null,
      researchPortfolio: null,
    }),
    "partial",
  );
  assert.equal(
    deriveState({
      isLoading: false,
      phase1Readiness: { overall_status: "ready" },
      benchmark: { candidates: [{}] },
      publicMarket: null,
      researchPortfolio: null,
      readinessError: false,
      benchmarkError: true,
    }),
    "partial",
  );
  assert.equal(
    deriveState({
      isLoading: false,
      phase1Readiness: { overall_status: "ready" },
      benchmark: { candidates: [{}] },
      publicMarket: null,
      researchPortfolio: null,
    }),
    "success",
  );
});

test("compose preserves backend candidate order and never re-ranks", () => {
  const rows = mapCandidates(
    {
      top_candidate_id: "beta",
      candidates: [
        { candidate: { candidate_id: "alpha", title: "A" }, evidence_completeness: 0.2, risk_level: "high" },
        { candidate: { candidate_id: "beta", title: "B" }, evidence_completeness: 0.9, risk_level: "low" },
      ],
    },
    "fixture_only",
  );
  assert.deepEqual(rows.map((row) => row.candidateId), ["alpha", "beta"]);
  assert.equal(rows[0].rankIndex, 0);
  assert.equal(rows[1].isTopCandidate, true);
});

test("filters preserve relative order and do not invent rankings", () => {
  const filtered = filterCandidates(SAMPLE_CANDIDATES, {
    query: "",
    risk: "all",
    decision: "hold_for_credentials",
    topOnly: false,
  });
  assert.deepEqual(filtered.map((row) => row.candidateId), ["beta", "gamma"]);
  assert.ok(filtered[0].rankIndex < filtered[1].rankIndex);
});

test("large candidate sets stay ordered under filter and windowing", () => {
  const large = buildLargeCandidates(120);
  const filtered = filterCandidates(large, {
    query: "",
    risk: "high",
    decision: "all",
    topOnly: false,
  });
  for (let i = 1; i < filtered.length; i += 1) {
    assert.ok(filtered[i - 1].rankIndex < filtered[i].rankIndex);
  }
  const windowed = windowCandidates(large, 50, 50);
  assert.equal(windowed.visible.length, 50);
  assert.equal(windowed.visible[0].candidateId, "cand-0050");
  assert.equal(windowed.hasMoreBefore, true);
  assert.equal(windowed.hasMoreAfter, true);
  assert.deepEqual(
    windowed.visible.map((row) => row.rankIndex),
    Array.from({ length: 50 }, (_, i) => 50 + i),
  );
});

test("schema-version and malformed packets are rejected fail-closed", () => {
  assert.equal(validateEvidenceCockpitApiPacket(null).reason, "packet_not_object");
  assert.equal(
    validateEvidenceCockpitApiPacket({
      read_only: true,
      mutated: false,
      report_version: "v1",
      generated_at: "2026-09-03T00:00:00Z",
      ranked_candidates: [],
      pillars: [],
      trustos: { status: "unavailable" },
      governor: { status: "unavailable" },
      approval_ledger: { status: "unavailable" },
      fingerprint: {},
    }).reason,
    "schema_version_required",
  );
  assert.equal(
    validateEvidenceCockpitApiPacket({
      schema_version: "phase1-evidence-cockpit-v999",
      read_only: true,
      mutated: false,
      report_version: "v1",
      generated_at: "2026-09-03T00:00:00Z",
      ranked_candidates: [],
      pillars: [],
      trustos: { status: "unavailable" },
      governor: { status: "unavailable" },
      approval_ledger: { status: "unavailable" },
      fingerprint: {},
    }).reason,
    "schema_version_unsupported",
  );
  assert.equal(
    validateEvidenceCockpitApiPacket({
      schema_version: SCHEMA_V1,
      read_only: true,
      mutated: false,
      report_version: "v1",
      generated_at: "2026-09-03T00:00:00Z",
      ranked_candidates: [
        { candidate_id: "b", title: "B", rank_index: 1 },
        { candidate_id: "a", title: "A", rank_index: 0 },
      ],
      pillars: [{ pillar_id: "market_evidence" }],
      trustos: { status: "unavailable" },
      governor: { status: "unavailable" },
      approval_ledger: { status: "unavailable" },
      fingerprint: {},
    }).reason,
    "candidate_rank_index_out_of_order",
  );
  assert.equal(
    validateEvidenceCockpitApiPacket({
      schema_version: SCHEMA_V1,
      read_only: true,
      mutated: false,
      report_version: "v1",
      generated_at: "2026-09-03T00:00:00Z",
      ranked_candidates: [],
      pillars: [],
      trustos: { status: "unavailable", api_key: "sk-live-SHOULD-NOT" },
      governor: { status: "unavailable" },
      approval_ledger: { status: "unavailable" },
      fingerprint: {},
    }).reason,
    "secret_shaped_value_rejected",
  );
});

test("valid future packet requires schema_version fingerprint and control planes", () => {
  const result = validateEvidenceCockpitApiPacket({
    schema_version: SCHEMA_V1,
    read_only: true,
    mutated: false,
    report_version: "phase1-evidence-cockpit-v1",
    generated_at: "2026-09-03T00:00:00Z",
    ranked_candidates: [{ candidate_id: "a", title: "A", rank_index: 0 }],
    pillars: [{ pillar_id: "market_evidence", status: "available", summary: "ok", blocked_reasons: [] }],
    trustos: { status: "fixture", outcome: "advisory", blocked_reasons: [] },
    governor: { status: "simulated", outcome: "requires_approval", blocked_reasons: [] },
    approval_ledger: { status: "blocked", outcome: "pending", blocked_reasons: ["policy_missing"] },
    fingerprint: { read_only: true, network_calls: false, source_labels: [], source_families: [] },
  });
  assert.equal(result.ok, true);
});

test("freshness labels and stale detection are deterministic", () => {
  const now = Date.parse("2026-09-03T12:00:00Z");
  assert.equal(formatFreshnessLabel("2026-09-03T11:59:30Z", now), "fresh_<1m");
  assert.equal(formatFreshnessLabel("2026-09-03T10:00:00Z", now), "age_2h");
  assert.equal(formatFreshnessLabel("2026-08-01T12:00:00Z", now), "age_33d");
  assert.equal(formatFreshnessLabel(null, now), null);
  assert.equal(isStaleFreshness("age_2h"), false);
  assert.equal(isStaleFreshness("age_30h"), true);
  assert.equal(isStaleFreshness("age_2d"), true);
});

test("evidence modes normalize across fixture manual simulated live-readonly", () => {
  assert.equal(normalizeEvidenceMode("fixture_only"), "fixture_only");
  assert.equal(normalizeEvidenceMode("manual_import"), "manual");
  assert.equal(normalizeEvidenceMode("simulated_run"), "simulated");
  assert.equal(normalizeEvidenceMode("live_readonly_probe"), "live_readonly");
  assert.equal(normalizeEvidenceMode(null), "unknown");
});

test("client-safe export validates schema and rejects secrets", () => {
  const exported = buildClientSafeExport(
    {
      state: "partial",
      schemaVersion: "composed-live",
      rankedCandidates: SAMPLE_CANDIDATES,
      warnings: ["fixture only"],
    },
    "2026-09-03T00:00:00Z",
  );
  assert.equal(exported.export_version, "first-phase-cockpit-client-safe-v1");
  assert.equal(exported.schema_version, "composed-live");
  assert.equal(exported.read_only, true);
  assert.doesNotMatch(JSON.stringify(exported), /sk-live-|ghp_|password/i);
  assert.throws(
    () =>
      buildClientSafeExport(
        {
          state: "success",
          rankedCandidates: [{ candidateId: "sk-live-abc", title: "x", rankIndex: 0 }],
          warnings: [],
        },
        "2026-09-03T00:00:00Z",
      ),
    /client_safe_export_rejected/,
  );
});

test("normalized render model preserves order and control-plane statuses", () => {
  const model = normalizeRenderModel({
    state: "partial",
    rankedCandidates: SAMPLE_CANDIDATES,
    controlPlanes: [
      { id: "trustos", status: "unavailable" },
      { id: "governor", status: "unavailable" },
      { id: "approval_ledger", status: "unavailable" },
    ],
    fingerprint: {
      evidenceMode: "fixture_only",
      schemaVersion: "composed-live",
      readOnly: true,
    },
  });
  assert.deepEqual(model.candidate_ids_in_order, ["alpha", "beta", "gamma"]);
  assert.equal(model.control_plane_statuses.trustos, "unavailable");
  assert.equal(model.schema_version, "composed-live");
});

test("source contracts: no client re-ranking and no API client duplication", async () => {
  const composeSource = await readFile(new URL("lib/composeCockpitViewModel.ts", featureRoot), "utf8");
  const filterSource = await readFile(new URL("lib/filterCandidates.ts", featureRoot), "utf8");
  const windowSource = await readFile(new URL("lib/windowCandidates.ts", featureRoot), "utf8");
  const pageSource = await readFile(new URL("../src/pages/FirstPhaseEvidenceCockpit.tsx", import.meta.url), "utf8");
  const apiClientSource = await readFile(new URL("../src/lib/canonicalEventsApi.ts", import.meta.url), "utf8");

  assert.doesNotMatch(composeSource, /\.sort\(/);
  assert.doesNotMatch(filterSource, /\.sort\(/);
  assert.doesNotMatch(windowSource, /\.sort\(/);
  assert.match(windowSource, /slice\(/);
  assert.match(pageSource, /useDeferredValue/);
  assert.match(pageSource, /useTransition/);
  assert.doesNotMatch(pageSource, /fetchPhase1Readiness|new WebSocket/);
  assert.doesNotMatch(apiClientSource, /first-phase-cockpit|evidence-cockpit/);
});

test("accessibility and focus contracts are present", async () => {
  const page = await readFile(new URL("../src/pages/FirstPhaseEvidenceCockpit.tsx", import.meta.url), "utf8");
  const table = await readFile(new URL("components/RankedCandidatesPanel.tsx", featureRoot), "utf8");
  const detail = await readFile(new URL("components/CandidateDetailPanel.tsx", featureRoot), "utf8");
  const banner = await readFile(new URL("components/CockpitStatusBanner.tsx", featureRoot), "utf8");

  assert.match(page, /Skip to ranked candidates/);
  assert.match(table, /aria-selected/);
  assert.match(table, /scope="col"/);
  assert.match(table, /role="grid"/);
  assert.match(table, /tabIndex=\{tabIndex\}/);
  assert.match(table, /Home/);
  assert.match(table, /End/);
  assert.match(table, /md:hidden/);
  assert.match(detail, /id="candidate-detail-panel"/);
  assert.match(banner, /partial/);
  assert.match(banner, /aria-live="polite"/);
});

test("demo fixture and control planes avoid secrets and document unavailable slots", async () => {
  const demo = await readFile(new URL("fixtures/demoPacket.ts", featureRoot), "utf8");
  const control = await readFile(new URL("components/ControlPlanePanel.tsx", featureRoot), "utf8");
  assert.doesNotMatch(demo, /sk-live-|ghp_|authorization|password|private_key/i);
  assert.match(demo, /schemaVersion: "composed-live"/);
  assert.match(demo, /id: "trustos"/);
  assert.match(control, /No launch, ads, orders, payment, publishing, or messaging authority/);
});

test("future packet validator and composed-live schema remain explicit", async () => {
  const validateSource = await readFile(new URL("lib/validateEvidencePacket.ts", featureRoot), "utf8");
  const contracts = await readFile(new URL("contracts/firstPhaseEvidencePacket.ts", featureRoot), "utf8");
  assert.match(validateSource, /schema_version_unsupported/);
  assert.match(validateSource, /Does not claim the endpoint exists/);
  assert.match(contracts, /EVIDENCE_COCKPIT_SCHEMA_VERSION/);
  assert.match(contracts, /CANDIDATE_WINDOW_SIZE/);
  assert.match(contracts, /"partial"/);
});

test("route wiring and api base authority remain unchanged", async () => {
  const mainSource = await readFile(new URL("../src/main.tsx", import.meta.url), "utf8");
  const hookSource = await readFile(new URL("hooks/useFirstPhaseEvidenceCockpit.ts", featureRoot), "utf8");
  const apiBase = await readFile(new URL("../src/lib/apiBase.ts", import.meta.url), "utf8");
  assert.match(mainSource, /\/operator\/first-phase/);
  assert.match(hookSource, /usePhase1Readiness/);
  assert.match(hookSource, /useBenchmarkMatrix/);
  assert.match(apiBase, /VITE_API_BASE_URL/);
});
