import type {
  BenchmarkMatrixView,
  Phase1Readiness,
  PublicMarketBenchmarkView,
  ResearchPortfolioSummaryView,
} from "@/lib/canonicalEventsApi";
import type {
  CandidatePillarCell,
  ControlPlaneSlot,
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

export function normalizeEvidenceMode(value: string | null | undefined): EvidenceMode {
  if (!value) return "unknown";
  const lowered = value.toLowerCase();
  if (lowered.includes("fixture")) return "fixture_only";
  if (lowered.includes("manual")) return "manual";
  if (lowered.includes("simul")) return "simulated";
  if (lowered.includes("live")) return "live_readonly";
  return "unknown";
}

export function deriveState(input: ComposeCockpitInput): EvidenceState {
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

function scoreStatus(score: number | null | undefined): CandidatePillarCell["status"] {
  if (score === null || score === undefined) return "unavailable";
  if (score >= 0.7) return "available";
  if (score >= 0.35) return "partial";
  return "blocked";
}

function buildPillarCells(item: BenchmarkMatrixView["candidates"][number], evidenceMode: EvidenceMode): CandidatePillarCell[] {
  return [
    {
      pillarId: "market_evidence",
      label: "Market",
      score: item.competition_evidence?.score ?? null,
      status: scoreStatus(item.competition_evidence?.score),
      detail: item.competition_evidence?.score !== undefined
        ? `competition score ${(item.competition_evidence.score * 100).toFixed(0)}%`
        : null,
    },
    {
      pillarId: "supplier_feasibility",
      label: "Supplier",
      score: item.supplier_evidence?.score ?? null,
      status: scoreStatus(item.supplier_evidence?.score),
      detail: item.supplier_evidence?.score !== undefined
        ? `supplier score ${(item.supplier_evidence.score * 100).toFixed(0)}%`
        : null,
    },
    {
      pillarId: "economics",
      label: "Economics",
      score: item.economics?.assumption_ratio !== undefined
        ? Math.max(0, 1 - item.economics.assumption_ratio)
        : null,
      status: item.economics?.margin_quality ? "partial" : "unavailable",
      detail: item.economics?.margin_quality
        ? `margin ${item.economics.margin_quality}`
        : null,
    },
    {
      pillarId: "provenance",
      label: "Provenance",
      score: null,
      status: evidenceMode === "unknown" ? "unavailable" : "available",
      detail: evidenceMode,
    },
    {
      pillarId: "freshness",
      label: "Freshness",
      score: null,
      status: "partial",
      detail: "portfolio freshness when available",
    },
    {
      pillarId: "consumer_attention",
      label: "Attention",
      score: null,
      status: "unavailable",
      detail: "consumer_attention_api_unavailable",
    },
  ];
}

function mapCandidates(
  benchmark: BenchmarkMatrixView | null,
  evidenceMode: EvidenceMode,
): RankedCandidateRow[] {
  if (!benchmark?.candidates?.length) return [];
  // Preserve backend order exactly — never sort or re-rank.
  return benchmark.candidates.map((item, rankIndex) => ({
    candidateId: item.candidate.candidate_id,
    title: item.candidate.title,
    rankIndex,
    evidenceCompleteness: item.evidence_completeness ?? null,
    supplierScore: item.supplier_evidence?.score ?? null,
    competitionScore: item.competition_evidence?.score ?? null,
    economicsLabel: item.economics?.margin_quality ?? null,
    assumptionRatio: item.economics?.assumption_ratio ?? null,
    commercialDecision: item.commercial_decision ?? null,
    nextBestAction: item.next_best_action ?? null,
    riskLevel: item.risk_level ?? null,
    validationPriority: item.validation_priority?.priority ?? null,
    validationTarget: item.validation_priority?.target ?? null,
    sourceFamily: "benchmark_matrix",
    evidenceMode,
    isTopCandidate: item.candidate.candidate_id === benchmark.top_candidate_id,
    pillarCells: buildPillarCells(item, evidenceMode),
  }));
}

function buildPillars(input: ComposeCockpitInput, evidenceMode: EvidenceMode): EvidencePillar[] {
  const { phase1Readiness: readiness, benchmark, publicMarket, researchPortfolio } = input;
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
      sourceFamily: publicMarket ? "public_market_benchmark" : benchmark ? "benchmark_matrix" : null,
      evidenceMode,
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
      sourceFamily: null,
      evidenceMode: null,
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
      sourceFamily: "phase1_readiness",
      evidenceMode,
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
      sourceFamily: "phase1_readiness",
      evidenceMode: "simulated",
      blockedReasons: [],
    },
    {
      id: "provenance",
      label: "Provenance",
      status: evidenceMode === "unknown" ? "unavailable" : "available",
      summary: `Evidence mode: ${evidenceMode.replace(/_/g, " ")}`,
      provenance: evidenceMode,
      freshness: null,
      sourceFamily: "benchmark_matrix",
      evidenceMode,
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
      sourceFamily: researchPortfolio ? "research_portfolio" : null,
      evidenceMode: researchPortfolio ? evidenceMode : null,
      blockedReasons: [],
    },
  ];
}

function buildControlPlanes(): ControlPlaneSlot[] {
  // Until GET /api/phase1/evidence-cockpit merges, keep explicit unavailable slots.
  return [
    {
      id: "trustos",
      label: "TrustOS",
      status: "unavailable",
      outcome: null,
      nextBestAction: null,
      blockedReasons: ["trustos_api_unavailable"],
      notes: [
        "Requires future GET /api/phase1/evidence-cockpit trustos slot aligned to TrustOSReport.to_dict(client_safe=True).",
      ],
    },
    {
      id: "governor",
      label: "Governor",
      status: "unavailable",
      outcome: null,
      nextBestAction: null,
      blockedReasons: ["governor_api_unavailable"],
      notes: [
        "Requires future governor slot from ResourceExecutionGovernorReport.to_dict() (offline simulation only).",
      ],
    },
    {
      id: "approval_ledger",
      label: "Approval Ledger",
      status: "unavailable",
      outcome: null,
      nextBestAction: null,
      blockedReasons: ["approval_ledger_api_unavailable"],
      notes: ["Approval Ledger remains a pre-integration gate; no browser authority."],
    },
  ];
}

export function composeCockpitViewModel(input: ComposeCockpitInput): FirstPhaseEvidencePacket {
  const state = deriveState(input);
  const evidenceMode = normalizeEvidenceMode(
    input.benchmark?.evidence_mode ?? input.publicMarket?.evidence_mode,
  );
  const rankedCandidates = mapCandidates(input.benchmark, evidenceMode);
  const pillars = buildPillars(input, evidenceMode);
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
  unavailableReasons.push("trustos_api_unavailable");
  unavailableReasons.push("governor_api_unavailable");
  unavailableReasons.push("approval_ledger_api_unavailable");

  const sourceLabels = [
    input.phase1Readiness ? "phase1-readiness" : null,
    input.benchmark ? "benchmark-matrix" : null,
    input.publicMarket ? "public-market-benchmark" : null,
    input.researchPortfolio ? "research-portfolio" : null,
  ].filter((label): label is string => Boolean(label));

  const sourceFamilies = [
    input.phase1Readiness ? "phase1_readiness" : null,
    input.benchmark ? "benchmark_matrix" : null,
    input.publicMarket ? "public_market_benchmark" : null,
    input.researchPortfolio ? "research_portfolio" : null,
  ].filter((label): label is string => Boolean(label));

  return {
    state,
    rankedCandidates,
    pillars,
    controlPlanes: buildControlPlanes(),
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
      sourceLabels,
      sourceFamilies,
      reportVersion: null,
      generatedAt: null,
    },
    blockedReasons,
    unavailableReasons,
    warnings,
  };
}
