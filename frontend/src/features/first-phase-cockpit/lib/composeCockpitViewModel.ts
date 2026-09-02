import type {
  BenchmarkMatrixView,
  Phase1Readiness,
  PublicMarketBenchmarkView,
  ResearchPortfolioSummaryView,
} from "@/lib/canonicalEventsApi";
import type {
  EvidenceMode,
  EvidencePillar,
  EvidenceState,
  FirstPhaseEvidencePacket,
  RankedCandidateRow,
} from "../contracts/firstPhaseEvidencePacket";

export interface ComposeCockpitInput {
  phase1Readiness: Phase1Readiness | null;
  benchmark: BenchmarkMatrixView | null;
  publicMarket: PublicMarketBenchmarkView | null;
  researchPortfolio: ResearchPortfolioSummaryView | null;
  readinessError: boolean;
  benchmarkError: boolean;
  publicMarketError: boolean;
  researchError: boolean;
  isLoading: boolean;
}

function normalizeEvidenceMode(value: string | null | undefined): EvidenceMode {
  if (!value) return "unknown";
  if (value.includes("fixture")) return "fixture_only";
  if (value.includes("manual")) return "manual";
  if (value.includes("simul")) return "simulated";
  if (value.includes("live")) return "live_readonly";
  return "unknown";
}

function deriveState(input: ComposeCockpitInput): EvidenceState {
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

function mapCandidates(
  benchmark: BenchmarkMatrixView | null,
): RankedCandidateRow[] {
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
    isTopCandidate: item.candidate.candidate_id === benchmark.top_candidate_id,
  }));
}

function buildPillars(input: ComposeCockpitInput): EvidencePillar[] {
  const { phase1Readiness: readiness, benchmark, publicMarket, researchPortfolio } = input;
  const evidenceMode = normalizeEvidenceMode(benchmark?.evidence_mode ?? publicMarket?.evidence_mode);
  const freshness = researchPortfolio?.quality
    ? `${(researchPortfolio.quality.research_freshness * 100).toFixed(0)}%`
    : null;

  return [
    {
      id: "market_evidence",
      label: "Market evidence",
      status: publicMarket || benchmark ? "available" : "unavailable",
      summary: publicMarket
        ? `${publicMarket.competitor_offers_observed} observed offers · ${(publicMarket.pricing_coverage * 100).toFixed(0)}% pricing coverage`
        : benchmark
          ? `Benchmark matrix loaded with ${benchmark.candidates.length} candidate(s)`
          : "Market evidence endpoint unavailable",
      provenance: evidenceMode,
      freshness,
      blockedReasons: publicMarket?.remaining_supplier_blocker
        ? [publicMarket.remaining_supplier_blocker]
        : [],
    },
    {
      id: "consumer_attention",
      label: "Consumer attention",
      status: "unavailable",
      summary: "Consumer-attention packet is not exposed by the current frontend API authority.",
      provenance: null,
      freshness: null,
      blockedReasons: ["consumer_attention_api_unavailable"],
    },
    {
      id: "supplier_feasibility",
      label: "Supplier feasibility",
      status: readiness?.supplier_readiness?.status === "blocked"
        ? "blocked"
        : readiness?.supplier_readiness
          ? "partial"
          : "unavailable",
      summary: readiness?.supplier_readiness
        ? `${readiness.supplier_readiness.observed_field_count} observed fields · ${(readiness.supplier_readiness.coverage * 100).toFixed(0)}% coverage`
        : "Supplier readiness unavailable",
      provenance: evidenceMode,
      freshness: null,
      blockedReasons: readiness?.credential_readiness?.credentials_present === false
        ? ["credential_missing"]
        : [],
    },
    {
      id: "economics",
      label: "Economics",
      status: readiness?.commerce_run_readiness ? "partial" : "unavailable",
      summary: readiness?.commerce_run_readiness
        ? `Run quality ${readiness.commerce_run_readiness.run_quality} · confidence ${(readiness.commerce_run_readiness.overall_confidence * 100).toFixed(0)}%`
        : "Commerce-run economics unavailable",
      provenance: "derived",
      freshness: null,
      blockedReasons: [],
    },
    {
      id: "provenance",
      label: "Provenance",
      status: evidenceMode === "unknown" ? "unavailable" : "available",
      summary: `Evidence mode: ${evidenceMode.replace(/_/g, " ")}`,
      provenance: evidenceMode,
      freshness: null,
      blockedReasons: [],
    },
    {
      id: "freshness",
      label: "Freshness",
      status: freshness ? "available" : "partial",
      summary: freshness
        ? `Research freshness ${freshness}`
        : "Freshness signals unavailable from research portfolio",
      provenance: researchPortfolio ? "derived" : null,
      freshness,
      blockedReasons: [],
    },
  ];
}

export function composeCockpitViewModel(input: ComposeCockpitInput): FirstPhaseEvidencePacket {
  const state = deriveState(input);
  const rankedCandidates = mapCandidates(input.benchmark);
  const pillars = buildPillars(input);
  const warnings = [
    ...(input.benchmark?.warnings ?? []),
    ...(input.publicMarket?.warnings ?? []),
    ...(input.phase1Readiness?.advisory_warnings ?? []),
  ];
  const blockedReasons = [
    ...(input.phase1Readiness?.blocking_gates ?? []),
    ...(input.phase1Readiness?.forbidden_next_phases ?? []),
  ];
  const unavailableReasons: string[] = [];
  if (input.readinessError) unavailableReasons.push("phase1_readiness_unavailable");
  if (input.benchmarkError) unavailableReasons.push("benchmark_matrix_unavailable");
  if (input.publicMarketError) unavailableReasons.push("public_market_benchmark_unavailable");
  if (input.researchError) unavailableReasons.push("research_portfolio_unavailable");
  unavailableReasons.push("consumer_attention_api_unavailable");

  const evidenceMode = normalizeEvidenceMode(
    input.benchmark?.evidence_mode ?? input.publicMarket?.evidence_mode,
  );

  return {
    state,
    rankedCandidates,
    pillars,
    controlPlanes: [
      {
        id: "trustos",
        label: "TrustOS",
        status: "unavailable",
        outcome: null,
        blockedReasons: ["trustos_api_unavailable"],
        notes: ["Requires future GET /api/phase1/evidence-cockpit trustos slot."],
      },
      {
        id: "governor",
        label: "Governor",
        status: "unavailable",
        outcome: null,
        blockedReasons: ["governor_api_unavailable"],
        notes: ["Requires future GET /api/phase1/evidence-cockpit governor slot."],
      },
      {
        id: "approval_ledger",
        label: "Approval Ledger",
        status: "unavailable",
        outcome: null,
        blockedReasons: ["approval_ledger_api_unavailable"],
        notes: ["Approval Ledger remains a pre-integration gate; no browser authority."],
      },
    ],
    fingerprint: {
      evidenceMode,
      overallStatus: input.phase1Readiness?.overall_status ?? null,
      nextBestAction:
        input.benchmark?.next_best_action
        ?? input.publicMarket?.next_best_action
        ?? input.phase1Readiness?.next_best_action
        ?? null,
      readOnly: Boolean(
        input.phase1Readiness?.read_only
        && (input.benchmark?.read_only ?? true)
        && (input.publicMarket?.read_only ?? true),
      ),
      networkCalls: Boolean(
        input.phase1Readiness?.network_calls
        || input.benchmark?.network_calls,
      ),
      sourceLabels: [
        input.phase1Readiness ? "phase1-readiness" : null,
        input.benchmark ? "benchmark-matrix" : null,
        input.publicMarket ? "public-market-benchmark" : null,
        input.researchPortfolio ? "research-portfolio" : null,
      ].filter((label): label is string => Boolean(label)),
    },
    blockedReasons,
    unavailableReasons,
    warnings,
  };
}
