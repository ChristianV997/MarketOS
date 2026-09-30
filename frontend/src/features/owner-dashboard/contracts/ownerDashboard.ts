/**
 * Owner dashboard view model.
 *
 * Built once, at the boundary (lib/adaptDiscoveryRun.ts), from the existing
 * offline opportunity-discovery response (services/opportunity_discovery,
 * DiscoveryRun.to_dict()). This is a display model, not a new API contract.
 * Nothing here scores, ranks, or computes economics: rank, readiness,
 * recommendation and every money value are the provider's, shown as sent.
 */

/** Where the data came from. Only "fixture_demo" is produced today. */
export type DataMode = "fixture_demo" | "live_readonly";

/** Provider readiness vocabulary; unrecognised values map to "unknown". */
export type Readiness = "ready" | "not_ready" | "blocked" | "unknown";

/** How a money line is grounded, from the provider's provenance / evidence_state. */
export type EconomicsBasis = "observed" | "manual" | "derived" | "assumed" | "fixture" | "unknown";

/** A money value is either a real amount (zero included) or explicitly unavailable. */
export type MoneyValue =
  | { kind: "amount"; numeric: number; raw: string; currency: string | null; basis: EconomicsBasis }
  | { kind: "unavailable" };

export type RatioValue = { kind: "ratio"; numeric: number; raw: string } | { kind: "unavailable" };

/**
 * How a line relates to inputs the provider listed as missing for its scenario.
 *  - ok: no missing-input concern.
 *  - input_missing: the line is one of the missing inputs; the provider's value is a placeholder, so it is unavailable.
 *  - depends_on_missing: a total built from lines that include missing inputs; unavailable rather than misleading.
 *  - excludes_missing: a real non-zero amount that still leaves out a missing part; shown with a caveat.
 */
export type LineState = "ok" | "input_missing" | "depends_on_missing" | "excludes_missing";

export interface OwnerEconomicsLine {
  key: string;
  label: string;
  money: MoneyValue;
  state: LineState;
}

export interface OwnerScenario {
  /** Provider scenario key, e.g. "best" | "base" | "worst". */
  name: string;
  providerLabel: string | null;
  status: "available" | "unavailable";
  /** True when the provider listed missing inputs for this scenario; its totals are then not shown. */
  incomplete: boolean;
  lines: OwnerEconomicsLine[];
  ratios: Record<string, RatioValue>;
  missingInputs: string[];
}

export interface OwnerEvidenceItem {
  id: string;
  area: string | null;
  status: string | null;
  evidenceClass: string | null;
  sourceType: string | null;
  sourceRef: string | null;
  freshness: string | null;
  conflicting: boolean;
}

export type UnrankedReason = "needs_evidence" | "blocked" | "ready_unscored" | "not_ranked";

export interface OwnerCandidate {
  /** Stable identity: the provider's candidate_id. Never re-derived or re-numbered. */
  candidateId: string;
  name: string;
  category: string | null;
  offeringKind: string | null;
  /** 1-based position in the provider's ranked_candidate_ids; null when the provider did not rank it. */
  rank: number | null;
  unrankedReason: UnrankedReason | null;
  recommendation: string | null;
  readiness: Readiness;
  rawReadiness: string | null;
  synthesisScore: number | null;
  synthesisRecommendation: string | null;
  /** Provider metric: share of evidence items marked observed_fact (0..1). */
  evidenceConfidence: number | null;
  fatalGates: string[];
  blockers: string[];
  evidenceGaps: string[];
  evidenceClasses: string[];
  evidence: OwnerEvidenceItem[];
  scenarios: OwnerScenario[];
  economicsStatus: string | null;
  economicsMissingInputs: string[];
  nextEvidence: string[];
  sensitivityDrivers: string[];
  /** True only if the provider claimed an external action was allowed (treated as an integrity problem). */
  providerClaimedExternalAction: boolean;
}

export interface OwnerRun {
  providerStatus: string | null;
  executionClassification: string | null;
  nextBestAction: string | null;
  blockers: string[];
  fingerprint: string | null;
  /** Provider safety flags that deviate from the read-only contract. */
  safetyViolations: string[];
  safetyPresent: boolean;
  candidates: OwnerCandidate[];
  /** Skipped provider records, with a short reason each. */
  dropped: string[];
}

export type NoticeTone = "info" | "warning" | "danger";

export interface OwnerNotice {
  id:
    | "demo_data"
    | "freshness_unknown"
    | "stale"
    | "evidence_freshness"
    | "partial_records"
    | "provider_integrity";
  tone: NoticeTone;
  title: string;
  detail: string;
}

export interface ReadinessSummary {
  total: number;
  rankedCount: number;
  researchReadyCount: number;
  needsEvidenceCount: number;
  blockedCount: number;
  readyUnscoredCount: number;
  /** Always false: this dashboard is advisory and cannot authorize a launch. */
  launchAuthorized: false;
}

export type PerformanceProvenance = "observed" | "fixture";

export interface PerformancePoint {
  periodLabel: string;
  /** null means "not available"; it is never coerced to zero. */
  value: number | null;
}

export interface PerformanceSeries {
  id: string;
  label: string;
  unit: "count" | "currency" | "ratio";
  currency?: string;
  provenance: PerformanceProvenance;
  points: PerformancePoint[];
}

export type PerformanceModel =
  | { status: "unavailable"; reason: string }
  | { status: "fixture_demo" | "observed"; series: PerformanceSeries[]; missingPoints: number };

export type OwnerViewStatus = "loading" | "unavailable" | "malformed" | "empty" | "ready";

export interface OwnerDashboardViewModel {
  status: OwnerViewStatus;
  dataMode: DataMode;
  notices: OwnerNotice[];
  /** Present for "unavailable" and "malformed". Both are recoverable with a retry. */
  error: { code: string; message: string } | null;
  run: {
    providerStatus: string | null;
    executionClassification: string | null;
    nextBestAction: string | null;
    fingerprintShort: string | null;
    blockers: string[];
  } | null;
  summary: ReadinessSummary | null;
  ranked: OwnerCandidate[];
  unranked: OwnerCandidate[];
  performance: PerformanceModel;
  saveToPortfolio: { enabled: false; reason: string };
}

/** What a source hands to the composer. `run` is the untrusted provider response. */
export interface OwnerSourcePayload {
  run: unknown;
  /** ISO timestamp of the data, when the source knows one. The provider response carries none. */
  asOf: string | null;
  performance: PerformanceSeries[] | null;
}

export interface OwnerDashboardSource {
  id: string;
  dataMode: DataMode;
  load(): Promise<OwnerSourcePayload>;
}

export type OwnerLoadState =
  | { status: "loading" }
  | { status: "error"; code?: string }
  | { status: "success"; payload: OwnerSourcePayload };
