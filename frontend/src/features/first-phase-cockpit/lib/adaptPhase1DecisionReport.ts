import type {
  DecisionCategoryRow,
  DecisionReportState,
  EvidenceAuthorityKind,
  Phase1DecisionReportView,
} from "../contracts/phase1DecisionReport";

/** Minimal structural shape of GET /api/phase1/readiness (stable on main). */
export interface Phase1ReadinessSource {
  overall_status?: string;
  overall_score?: number;
  blocking_gates?: string[];
  advisory_warnings?: string[];
  next_best_action?: string;
  next_best_prompt_hint?: string;
  allowed_next_phases?: string[];
  forbidden_next_phases?: string[];
  read_only?: boolean;
  mutated?: boolean;
  network_calls?: boolean;
  supplier_readiness?: {
    status?: string;
    observed_field_count?: number;
    coverage?: number;
    price_observed?: boolean;
    inventory_observed?: boolean;
    shipping_observed?: boolean;
    source?: string;
  };
  competition_readiness?: {
    status?: string;
    observed_offer_count?: number;
    pricing_coverage?: number;
  };
  opportunity_readiness?: {
    status?: string;
    candidate_count?: number;
    confidence?: number;
  };
  research_readiness?: {
    status?: string;
    candidate_count?: number;
  };
  commerce_run_readiness?: {
    status?: string;
    run_quality?: string;
    overall_confidence?: number;
    evidence_completeness?: number;
    assumption_percentage?: number | null;
  };
  credential_readiness?: {
    status?: string;
    provider?: string;
    credentials_present?: boolean;
    live_flag_enabled?: boolean;
  };
  validation_pack_readiness?: {
    status?: string;
    report_present?: boolean;
    live_probe_status?: string;
  };
  safety_readiness?: {
    status?: string;
    read_only?: boolean;
    no_mutation_authority?: boolean;
  };
  evidence_summary?: Record<string, unknown>;
  provenance?: Record<string, unknown>;
  score_contributions?: Record<
    string,
    { status?: string; weight?: number; status_value?: number; points?: number }
  >;
}

const CATEGORY_LABELS: Record<string, string> = {
  supplier: "Supplier",
  competition: "Competition",
  opportunity: "Opportunity",
  research: "Research",
  commerce: "Commerce run",
  evaluation: "Evaluation",
  events: "Events",
  credentials: "Credentials",
  validation_pack: "Validation pack",
  deployment: "Deployment",
  safety: "Safety",
};

function humanize(value: string | null | undefined): string {
  return String(value ?? "").replace(/_/g, " ").trim() || "unavailable";
}

export function classifyEvidenceAuthority(
  status: string | null | undefined,
  categoryKey?: string,
): EvidenceAuthorityKind {
  const normalized = String(status ?? "").toLowerCase();
  if (normalized === "live_observed") {
    // Only authenticated supplier live_observed is live supplier proof.
    return categoryKey === "supplier" ? "live_supplier_proof" : "partial_or_degraded";
  }
  if (normalized === "ready") return "structural_ready";
  if (normalized === "blocked") return "blocked";
  if (normalized === "partially_ready" || normalized === "degraded") return "partial_or_degraded";
  if (normalized === "fixture_only" || normalized.includes("fixture") || normalized.includes("manual")) {
    return "fixture_or_manual";
  }
  if (!normalized || normalized === "unknown" || normalized === "not_configured") return "unavailable";
  return "fixture_or_manual";
}

/**
 * live_observed on competition is public/live competition context — not authenticated
 * supplier proof. Only supplier_readiness.live_observed counts as live supplier proof.
 */
export function isLiveSupplierProof(supplierStatus: string | null | undefined): boolean {
  return String(supplierStatus ?? "").toLowerCase() === "live_observed";
}

function categoryDetail(key: string, source: Phase1ReadinessSource): string {
  if (key === "supplier") {
    const s = source.supplier_readiness ?? {};
    return `${s.observed_field_count ?? 0} fields · coverage ${Number(s.coverage ?? 0).toFixed(0)}% · source ${humanize(s.source)}`;
  }
  if (key === "competition") {
    const c = source.competition_readiness ?? {};
    return `${c.observed_offer_count ?? 0} offers · pricing coverage ${Number(c.pricing_coverage ?? 0).toFixed(0)}%`;
  }
  if (key === "opportunity") {
    const o = source.opportunity_readiness ?? {};
    return `${o.candidate_count ?? 0} candidates · confidence ${Number(o.confidence ?? 0).toFixed(2)}`;
  }
  if (key === "commerce") {
    const m = source.commerce_run_readiness ?? {};
    return `quality ${humanize(m.run_quality)} · completeness ${Number(m.evidence_completeness ?? 0).toFixed(2)}`;
  }
  if (key === "credentials") {
    const c = source.credential_readiness ?? {};
    return `${humanize(c.provider)} · credentials ${c.credentials_present ? "present" : "missing"} · live flag ${c.live_flag_enabled ? "on" : "off"}`;
  }
  if (key === "validation_pack") {
    const v = source.validation_pack_readiness ?? {};
    return `report ${v.report_present ? "present" : "absent"} · probe ${humanize(v.live_probe_status)}`;
  }
  if (key === "safety") {
    const s = source.safety_readiness ?? {};
    return `read-only ${s.read_only ? "yes" : "no"} · mutation authority ${s.no_mutation_authority ? "none" : "present"}`;
  }
  return humanize(source.score_contributions?.[key]?.status);
}

function buildCategories(source: Phase1ReadinessSource): DecisionCategoryRow[] {
  const contributions = source.score_contributions ?? {};
  const keys = Object.keys(contributions).length
    ? Object.keys(contributions).sort()
    : ["supplier", "competition", "opportunity", "commerce", "credentials", "validation_pack", "safety"];
  return keys.map((key) => {
    const contrib = contributions[key] ?? {};
    const status =
      contrib.status
      ?? (key === "supplier"
        ? source.supplier_readiness?.status
        : key === "competition"
          ? source.competition_readiness?.status
          : key === "opportunity"
            ? source.opportunity_readiness?.status
            : key === "commerce"
              ? source.commerce_run_readiness?.status
              : key === "credentials"
                ? source.credential_readiness?.status
                : key === "validation_pack"
                  ? source.validation_pack_readiness?.status
                  : key === "safety"
                    ? source.safety_readiness?.status
                    : "unknown");
    const authority = classifyEvidenceAuthority(status, key);
    return {
      key,
      label: CATEGORY_LABELS[key] ?? humanize(key),
      status: humanize(status),
      authority,
      detail: categoryDetail(key, source),
      points: typeof contrib.points === "number" ? contrib.points : null,
      weight: typeof contrib.weight === "number" ? contrib.weight : null,
    };
  });
}

function evidenceSummaryLines(summary: Record<string, unknown> | undefined): string[] {
  if (!summary) return [];
  const lines: string[] = [];
  const pairs: Array<[string, unknown]> = [
    ["Live supplier fields", summary.live_observed_supplier_fields],
    ["Live competitor offers", summary.live_observed_competitor_offers],
    ["Evidence completeness", summary.overall_evidence_completeness],
    ["Overall confidence", summary.overall_confidence],
    ["Assumption percentage", summary.assumption_percentage],
    ["Benchmark matrix", summary.benchmark_matrix_status],
    ["Best candidate", summary.best_candidate_id],
    ["Public-market status", summary.public_market_benchmark_status],
    ["Remaining supplier blocker", summary.remaining_supplier_blocker],
  ];
  for (const [label, value] of pairs) {
    if (value === undefined || value === null || value === "") continue;
    lines.push(`${label}: ${typeof value === "number" ? value : humanize(String(value))}`);
  }
  return lines;
}

function provenanceLines(provenance: Record<string, unknown> | undefined): string[] {
  if (!provenance) return [];
  return Object.keys(provenance)
    .sort()
    .map((key) => `${humanize(key)}: ${humanize(String(provenance[key]))}`);
}

function assumptionLabels(source: Phase1ReadinessSource): string[] {
  const labels: string[] = [];
  const pct = source.commerce_run_readiness?.assumption_percentage;
  if (pct != null) {
    labels.push(`Commerce assumption share: ${(Number(pct) * 100).toFixed(0)}% (planning assumption, not proof)`);
  }
  const summaryPct = source.evidence_summary?.assumption_percentage;
  if (summaryPct != null && summaryPct !== pct) {
    labels.push(`Evidence assumption share: ${(Number(summaryPct) * 100).toFixed(0)}% (planning assumption)`);
  }
  labels.push("Price, CPA, CTR, budget, and scale thresholds remain planning assumptions when present upstream.");
  labels.push("Fixture/manual signals are not authenticated supplier proof and do not authorize spend, publish, or orders.");
  return labels;
}

export function resolveDecisionReportState(input: {
  isLoading: boolean;
  isError: boolean;
  data: Phase1ReadinessSource | null | undefined;
}): DecisionReportState {
  if (input.isLoading) return "loading";
  if (input.isError && !input.data) return "error";
  if (!input.data) return "empty";
  return "success";
}

export function adaptPhase1DecisionReport(input: {
  isLoading: boolean;
  isError: boolean;
  errorMessage?: string | null;
  data: Phase1ReadinessSource | null | undefined;
}): Phase1DecisionReportView {
  const state = resolveDecisionReportState(input);
  if (state === "loading") {
    return {
      state,
      overallStatus: null,
      overallScore: null,
      nextBestAction: null,
      nextBestPromptHint: null,
      blockingGates: [],
      advisoryWarnings: [],
      allowedNextPhases: [],
      forbiddenNextPhases: [],
      assumptionPercentage: null,
      assumptionLabels: [],
      evidenceSummaryLines: [],
      provenanceLines: [],
      categories: [],
      supplierIsLiveProof: false,
      competitionIsLiveObserved: false,
      readOnly: true,
      networkCalls: false,
      mutated: false,
      errorMessage: null,
      emptyMessage: null,
    };
  }
  if (state === "error") {
    return {
      state,
      overallStatus: null,
      overallScore: null,
      nextBestAction: null,
      nextBestPromptHint: null,
      blockingGates: [],
      advisoryWarnings: [],
      allowedNextPhases: [],
      forbiddenNextPhases: [],
      assumptionPercentage: null,
      assumptionLabels: [],
      evidenceSummaryLines: [],
      provenanceLines: [],
      categories: [],
      supplierIsLiveProof: false,
      competitionIsLiveObserved: false,
      readOnly: true,
      networkCalls: false,
      mutated: false,
      errorMessage:
        input.errorMessage
        ?? "Phase 1 readiness endpoint is unavailable. No decision report can be composed.",
      emptyMessage: null,
    };
  }
  if (state === "empty") {
    return {
      state,
      overallStatus: null,
      overallScore: null,
      nextBestAction: null,
      nextBestPromptHint: null,
      blockingGates: [],
      advisoryWarnings: [],
      allowedNextPhases: [],
      forbiddenNextPhases: [],
      assumptionPercentage: null,
      assumptionLabels: [],
      evidenceSummaryLines: [],
      provenanceLines: [],
      categories: [],
      supplierIsLiveProof: false,
      competitionIsLiveObserved: false,
      readOnly: true,
      networkCalls: false,
      mutated: false,
      errorMessage: null,
      emptyMessage: "No Phase 1 readiness report is loaded yet. Waiting for GET /api/phase1/readiness.",
    };
  }

  const data = input.data!;
  const supplierStatus = data.supplier_readiness?.status ?? null;
  const competitionStatus = data.competition_readiness?.status ?? null;
  return {
    state,
    overallStatus: data.overall_status ?? null,
    overallScore: typeof data.overall_score === "number" ? data.overall_score : null,
    nextBestAction: data.next_best_action ?? null,
    nextBestPromptHint: data.next_best_prompt_hint ?? null,
    blockingGates: Array.isArray(data.blocking_gates) ? data.blocking_gates.map(String) : [],
    advisoryWarnings: Array.isArray(data.advisory_warnings) ? data.advisory_warnings.map(String) : [],
    allowedNextPhases: Array.isArray(data.allowed_next_phases) ? data.allowed_next_phases.map(String) : [],
    forbiddenNextPhases: Array.isArray(data.forbidden_next_phases) ? data.forbidden_next_phases.map(String) : [],
    assumptionPercentage:
      data.commerce_run_readiness?.assumption_percentage
      ?? (typeof data.evidence_summary?.assumption_percentage === "number"
        ? data.evidence_summary.assumption_percentage
        : null),
    assumptionLabels: assumptionLabels(data),
    evidenceSummaryLines: evidenceSummaryLines(data.evidence_summary),
    provenanceLines: provenanceLines(data.provenance),
    categories: buildCategories(data),
    supplierIsLiveProof: isLiveSupplierProof(supplierStatus),
    competitionIsLiveObserved: String(competitionStatus ?? "").toLowerCase() === "live_observed",
    readOnly: data.read_only !== false,
    networkCalls: Boolean(data.network_calls),
    mutated: Boolean(data.mutated),
    errorMessage: input.isError
      ? (input.errorMessage ?? "Readiness loaded with a transport warning; treat fields as partial.")
      : null,
    emptyMessage: null,
  };
}
