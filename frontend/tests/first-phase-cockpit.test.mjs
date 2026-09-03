import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const featureRoot = new URL("../src/features/first-phase-cockpit/", import.meta.url);

/** Facsimile of normalizeEvidenceMode / deriveState / compose mapping. */
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
  return "success";
}

function mapCandidates(benchmark, evidenceMode) {
  if (!benchmark?.candidates?.length) return [];
  return benchmark.candidates.map((item, rankIndex) => ({
    candidateId: item.candidate.candidate_id,
    title: item.candidate.title,
    rankIndex,
    evidenceCompleteness: item.evidence_completeness ?? null,
    supplierScore: item.supplier_evidence?.score ?? null,
    competitionScore: item.competition_evidence?.score ?? null,
    economicsLabel: item.economics?.margin_quality ?? null,
    commercialDecision: item.commercial_decision ?? null,
    nextBestAction: item.next_best_action ?? null,
    riskLevel: item.risk_level ?? null,
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

function validateEvidenceCockpitApiPacket(raw) {
  if (!raw || typeof raw !== "object") return { ok: false, reason: "packet_not_object" };
  if (raw.read_only !== true) return { ok: false, reason: "read_only_required" };
  if (raw.mutated !== false) return { ok: false, reason: "mutated_must_be_false" };
  if (typeof raw.report_version !== "string" || !raw.report_version) {
    return { ok: false, reason: "report_version_required" };
  }
  if (!Array.isArray(raw.ranked_candidates)) return { ok: false, reason: "ranked_candidates_required" };
  if (!Array.isArray(raw.pillars)) return { ok: false, reason: "pillars_required" };
  for (const candidate of raw.ranked_candidates) {
    if (!candidate || typeof candidate !== "object") return { ok: false, reason: "candidate_malformed" };
    if (typeof candidate.candidate_id !== "string" || typeof candidate.title !== "string") {
      return { ok: false, reason: "candidate_identity_required" };
    }
    if (typeof candidate.rank_index !== "number" || !Number.isInteger(candidate.rank_index) || candidate.rank_index < 0) {
      return { ok: false, reason: "candidate_rank_index_invalid" };
    }
  }
  for (const pillar of raw.pillars) {
    if (!pillar || typeof pillar !== "object") return { ok: false, reason: "pillar_malformed" };
    if (!PILLAR_IDS.has(pillar.pillar_id)) return { ok: false, reason: "pillar_id_invalid" };
  }
  for (const key of ["trustos", "governor", "approval_ledger"]) {
    if (!raw[key] || typeof raw[key] !== "object") return { ok: false, reason: `${key}_required` };
  }
  if (containsSecretShapedValue(raw)) return { ok: false, reason: "secret_shaped_value_rejected" };
  return { ok: true, packet: raw };
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

test("state transitions cover loading empty blocked unavailable stale success", () => {
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

  const topOnly = filterCandidates(SAMPLE_CANDIDATES, {
    query: "beta",
    risk: "medium",
    decision: "all",
    topOnly: true,
  });
  assert.deepEqual(topOnly.map((row) => row.candidateId), ["beta"]);
});

test("malformed evidence-cockpit packets are rejected fail-closed", () => {
  assert.equal(validateEvidenceCockpitApiPacket(null).reason, "packet_not_object");
  assert.equal(validateEvidenceCockpitApiPacket({ read_only: false, mutated: false }).reason, "read_only_required");
  assert.equal(
    validateEvidenceCockpitApiPacket({
      read_only: true,
      mutated: true,
      report_version: "v1",
      ranked_candidates: [],
      pillars: [],
      trustos: { status: "unavailable" },
      governor: { status: "unavailable" },
      approval_ledger: { status: "unavailable" },
    }).reason,
    "mutated_must_be_false",
  );
  assert.equal(
    validateEvidenceCockpitApiPacket({
      read_only: true,
      mutated: false,
      report_version: "v1",
      ranked_candidates: [{ candidate_id: "x", title: "X", rank_index: -1 }],
      pillars: [{ pillar_id: "market_evidence" }],
      trustos: { status: "unavailable" },
      governor: { status: "unavailable" },
      approval_ledger: { status: "unavailable" },
    }).reason,
    "candidate_rank_index_invalid",
  );
  assert.equal(
    validateEvidenceCockpitApiPacket({
      read_only: true,
      mutated: false,
      report_version: "v1",
      ranked_candidates: [],
      pillars: [{ pillar_id: "not_a_pillar" }],
      trustos: { status: "unavailable" },
      governor: { status: "unavailable" },
      approval_ledger: { status: "unavailable" },
    }).reason,
    "pillar_id_invalid",
  );
  assert.equal(
    validateEvidenceCockpitApiPacket({
      read_only: true,
      mutated: false,
      report_version: "v1",
      ranked_candidates: [],
      pillars: [],
      trustos: { status: "unavailable", api_key: "sk-live-SHOULD-NOT" },
      governor: { status: "unavailable" },
      approval_ledger: { status: "unavailable" },
    }).reason,
    "secret_shaped_value_rejected",
  );
});

test("valid future packet accepts required control-plane slots", () => {
  const result = validateEvidenceCockpitApiPacket({
    read_only: true,
    mutated: false,
    report_version: "phase1-evidence-cockpit-v1",
    generated_at: "2026-09-03T00:00:00Z",
    ranked_candidates: [{ candidate_id: "a", title: "A", rank_index: 0 }],
    pillars: [{ pillar_id: "market_evidence", status: "available", summary: "ok", blocked_reasons: [] }],
    trustos: { status: "fixture", outcome: "advisory", blocked_reasons: [] },
    governor: { status: "simulated", outcome: "requires_approval", blocked_reasons: [] },
    approval_ledger: { status: "blocked", outcome: "pending", blocked_reasons: ["policy_missing"] },
  });
  assert.equal(result.ok, true);
});

test("stale and unavailable evidence modes normalize deterministically", () => {
  assert.equal(normalizeEvidenceMode("fixture_only"), "fixture_only");
  assert.equal(normalizeEvidenceMode("manual_import"), "manual");
  assert.equal(normalizeEvidenceMode("simulated_run"), "simulated");
  assert.equal(normalizeEvidenceMode("live_readonly_probe"), "live_readonly");
  assert.equal(normalizeEvidenceMode("something_else"), "unknown");
  assert.equal(normalizeEvidenceMode(null), "unknown");
});

test("client-safe export omits secrets and rejects secret-shaped payloads", () => {
  const packet = {
    state: "success",
    rankedCandidates: SAMPLE_CANDIDATES,
    warnings: ["fixture only"],
  };
  const exported = buildClientSafeExport(packet, "2026-09-03T00:00:00Z");
  assert.equal(exported.read_only, true);
  assert.equal(exported.mutated, false);
  assert.equal(exported.network_calls, false);
  assert.doesNotMatch(JSON.stringify(exported), /sk-live-|ghp_|password/i);
  assert.throws(
    () =>
      buildClientSafeExport(
        { state: "success", rankedCandidates: [{ candidateId: "sk-live-abc", title: "x", rankIndex: 0 }], warnings: [] },
        "2026-09-03T00:00:00Z",
      ),
    /client_safe_export_rejected/,
  );
});

test("source contracts: no client re-ranking and no API client duplication", async () => {
  const composeSource = await readFile(new URL("lib/composeCockpitViewModel.ts", featureRoot), "utf8");
  const filterSource = await readFile(new URL("lib/filterCandidates.ts", featureRoot), "utf8");
  const pageSource = await readFile(new URL("../src/pages/FirstPhaseEvidenceCockpit.tsx", import.meta.url), "utf8");
  const apiClientSource = await readFile(new URL("../src/lib/canonicalEventsApi.ts", import.meta.url), "utf8");

  assert.doesNotMatch(composeSource, /\.sort\(/);
  assert.doesNotMatch(filterSource, /\.sort\(/);
  assert.match(composeSource, /Preserve backend order exactly/);
  assert.match(filterSource, /Never sorts/);
  assert.match(pageSource, /filterCandidates/);
  assert.match(pageSource, /serializeClientSafeExport/);
  assert.doesNotMatch(pageSource, /fetchPhase1Readiness|new WebSocket/);
  assert.doesNotMatch(apiClientSource, /first-phase-cockpit|evidence-cockpit/);
});

test("accessibility-critical controls are present in cockpit UI sources", async () => {
  const page = await readFile(new URL("../src/pages/FirstPhaseEvidenceCockpit.tsx", import.meta.url), "utf8");
  const table = await readFile(new URL("components/RankedCandidatesPanel.tsx", featureRoot), "utf8");
  const toolbar = await readFile(new URL("components/CockpitToolbar.tsx", featureRoot), "utf8");
  const banner = await readFile(new URL("components/CockpitStatusBanner.tsx", featureRoot), "utf8");

  assert.match(page, /Skip to ranked candidates/);
  assert.match(table, /aria-selected/);
  assert.match(table, /scope="col"/);
  assert.match(table, /<caption/);
  assert.match(table, /ArrowDown/);
  assert.match(table, /ArrowUp/);
  assert.match(toolbar, /aria-controls="ranked-candidates-table"/);
  assert.match(toolbar, /Search candidates/);
  assert.match(banner, /aria-live="polite"/);
  assert.match(banner, /role="status"/);
});

test("demo fixture and control planes avoid raw payload/secret rendering", async () => {
  const demo = await readFile(new URL("fixtures/demoPacket.ts", featureRoot), "utf8");
  const control = await readFile(new URL("components/ControlPlanePanel.tsx", featureRoot), "utf8");
  assert.doesNotMatch(demo, /sk-live-|ghp_|authorization|password|private_key/i);
  assert.match(demo, /id: "trustos"/);
  assert.match(demo, /id: "governor"/);
  assert.match(demo, /id: "approval_ledger"/);
  assert.match(control, /No launch, ads, orders, payment, publishing, or messaging authority/);
});

test("route wiring and future packet validator remain in place", async () => {
  const mainSource = await readFile(new URL("../src/main.tsx", import.meta.url), "utf8");
  const validateSource = await readFile(new URL("lib/validateEvidencePacket.ts", featureRoot), "utf8");
  const hookSource = await readFile(new URL("hooks/useFirstPhaseEvidenceCockpit.ts", featureRoot), "utf8");

  assert.match(mainSource, /\/operator\/first-phase/);
  assert.match(validateSource, /validateEvidenceCockpitApiPacket/);
  assert.match(validateSource, /mapApiPacketToViewModel/);
  assert.match(hookSource, /usePhase1Readiness/);
  assert.match(hookSource, /useBenchmarkMatrix/);
  assert.match(hookSource, /usePublicMarketBenchmark/);
  assert.match(hookSource, /useResearchPortfolios/);
});

test("api base / proxy authority remains unchanged for cockpit work", async () => {
  const apiBase = await readFile(new URL("../src/lib/apiBase.ts", import.meta.url), "utf8");
  const vite = await readFile(new URL("../vite.config.ts", import.meta.url), "utf8");
  assert.match(apiBase, /VITE_API_BASE_URL/);
  assert.match(apiBase, /VITE_API_URL/);
  assert.match(vite, /proxy/);
});
