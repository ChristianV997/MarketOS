/** Read-only first-phase evidence cockpit contract (frontend view model). */

/** Future GET /api/phase1/evidence-cockpit schema id. Composed live view uses composed-live. */
export const EVIDENCE_COCKPIT_SCHEMA_VERSION = "phase1-evidence-cockpit-v1" as const;

export const SUPPORTED_EVIDENCE_COCKPIT_SCHEMA_VERSIONS = new Set<string>([
  EVIDENCE_COCKPIT_SCHEMA_VERSION,
]);

export const CLIENT_SAFE_EXPORT_VERSION = "first-phase-cockpit-client-safe-v1" as const;

/** Default visible row window for large ranked sets (no virtualization dependency). */
export const CANDIDATE_WINDOW_SIZE = 50;

export type EvidenceState =
  | "loading"
  | "empty"
  | "blocked"
  | "unavailable"
  | "stale"
  | "partial"
  | "success";

export type EvidenceMode =
  | "fixture_only"
  | "manual"
  | "simulated"
  | "live_readonly"
  | "unknown";

/**
 * Source-family evidence class. Distinct from run-mode (`EvidenceMode`).
 * Live proof classes are never assigned from fixture/manual/simulated runs.
 */
export const EVIDENCE_CLASSES = [
  "fixture",
  "assumption",
  "derived",
  "public_observed",
  "supplier_claimed",
  "supplier_documented",
  "sample_verified",
  "direct_ship_verified",
  "live_order_verified",
  "live_sales_validated",
  "unavailable",
  "blocked",
] as const;

export type EvidenceClass = (typeof EVIDENCE_CLASSES)[number];

export const LIVE_PROOF_EVIDENCE_CLASSES = new Set<EvidenceClass>([
  "sample_verified",
  "direct_ship_verified",
  "live_order_verified",
  "live_sales_validated",
]);

export type ControlPlaneStatus =
  | "unavailable"
  | "fixture"
  | "simulated"
  | "stale"
  | "live_readonly"
  | "blocked";

export type PillarId =
  | "market_evidence"
  | "consumer_attention"
  | "supplier_feasibility"
  | "economics"
  | "provenance"
  | "freshness";

export type CandidateRiskFilter = "all" | "high" | "medium" | "low" | "unknown";
export type CandidateDecisionFilter = "all" | string;

export interface CandidatePillarCell {
  pillarId: PillarId;
  label: string;
  score: number | null;
  status: "available" | "partial" | "unavailable" | "blocked";
  detail: string | null;
  evidenceClass: EvidenceClass;
}

export type PromotionState = "hold" | "blocked" | "reject" | "defer" | "unavailable";

export interface MarketLaneView {
  origin: string | null;
  destination: string | null;
  currency: string | null;
}

export interface RankedCandidateRow {
  candidateId: string;
  title: string;
  sku: string | null;
  rankIndex: number;
  evidenceCompleteness: number | null;
  supplierScore: number | null;
  competitionScore: number | null;
  economicsLabel: string | null;
  assumptionRatio: number | null;
  commercialDecision: string | null;
  nextBestAction: string | null;
  riskLevel: string | null;
  validationPriority: string | null;
  validationTarget: string | null;
  sourceFamily: string | null;
  evidenceMode: EvidenceMode;
  evidenceClass: EvidenceClass;
  promotionState: PromotionState;
  marketLane: MarketLaneView | null;
  supplierOffer: string | null;
  confidence: number | null;
  assumptions: string[];
  missingEvidence: string[];
  conflicts: string[];
  isTopCandidate: boolean;
  pillarCells: CandidatePillarCell[];
}

export interface EvidencePillar {
  id: PillarId;
  label: string;
  status: "available" | "partial" | "unavailable" | "blocked";
  summary: string;
  provenance: string | null;
  freshness: string | null;
  sourceFamily: string | null;
  evidenceMode: EvidenceMode | null;
  evidenceClass: EvidenceClass;
  blockedReasons: string[];
}

export interface ControlPlaneSlot {
  id: "trustos" | "governor" | "approval_ledger";
  label: string;
  status: ControlPlaneStatus;
  outcome: string | null;
  nextBestAction: string | null;
  blockedReasons: string[];
  notes: string[];
}

export interface RunFingerprint {
  evidenceMode: EvidenceMode;
  overallStatus: string | null;
  nextBestAction: string | null;
  readOnly: boolean;
  networkCalls: boolean;
  sourceLabels: string[];
  sourceFamilies: string[];
  reportVersion: string | null;
  schemaVersion: string | null;
  generatedAt: string | null;
  freshnessLabel: string | null;
}

export interface FirstPhaseEvidencePacket {
  state: EvidenceState;
  rankedCandidates: RankedCandidateRow[];
  pillars: EvidencePillar[];
  controlPlanes: ControlPlaneSlot[];
  fingerprint: RunFingerprint;
  blockedReasons: string[];
  unavailableReasons: string[];
  warnings: string[];
}

export interface CandidateFilterState {
  query: string;
  risk: CandidateRiskFilter;
  decision: CandidateDecisionFilter;
  topOnly: boolean;
}

export interface ClientSafeCockpitExport {
  export_version: typeof CLIENT_SAFE_EXPORT_VERSION;
  schema_version: typeof EVIDENCE_COCKPIT_SCHEMA_VERSION | "composed-live";
  exported_at: string;
  read_only: true;
  mutated: false;
  network_calls: false;
  state: EvidenceState;
  evidence_mode: EvidenceMode;
  overall_status: string | null;
  next_best_action: string | null;
  source_labels: string[];
  source_families: string[];
  ranked_candidates: Array<{
    candidate_id: string;
    title: string;
    rank_index: number;
    evidence_completeness: number | null;
    supplier_score: number | null;
    competition_score: number | null;
    economics_label: string | null;
    commercial_decision: string | null;
    next_best_action: string | null;
    risk_level: string | null;
    is_top_candidate: boolean;
    evidence_class: EvidenceClass;
    sku: string | null;
    promotion_state: PromotionState;
    market_lane: MarketLaneView | null;
    confidence: number | null;
    assumptions: string[];
    missing_evidence: string[];
    conflicts: string[];
  }>;
  pillars: Array<{
    pillar_id: PillarId;
    status: EvidencePillar["status"];
    summary: string;
    blocked_reasons: string[];
  }>;
  control_planes: Array<{
    id: ControlPlaneSlot["id"];
    status: ControlPlaneStatus;
    outcome: string | null;
    blocked_reasons: string[];
  }>;
  warnings: string[];
  blocked_reasons: string[];
  unavailable_reasons: string[];
}

/**
 * Future backend contract (not merged): GET /api/phase1/evidence-cockpit
 * Aligns to existing Phase1/TrustOS/Governor `to_dict` / client_safe projections.
 * Requires schema_version in SUPPORTED_EVIDENCE_COCKPIT_SCHEMA_VERSIONS.
 */
export interface FirstPhaseEvidenceCockpitApiContract {
  schema_version: typeof EVIDENCE_COCKPIT_SCHEMA_VERSION;
  report_version: string;
  generated_at: string;
  evidence_mode: EvidenceMode;
  overall_status: string;
  ranked_candidates: Array<{
    candidate_id: string;
    title: string;
    rank_index: number;
    evidence_completeness: number | null;
    supplier_score: number | null;
    competition_score: number | null;
    economics_label: string | null;
    assumption_ratio: number | null;
    commercial_decision: string | null;
    next_best_action: string | null;
    risk_level: string | null;
    validation_priority: string | null;
    validation_target: string | null;
    source_family: string | null;
    is_top_candidate: boolean;
    pillar_cells?: Array<{
      pillar_id: PillarId;
      score: number | null;
      status: CandidatePillarCell["status"];
      detail: string | null;
    }>;
  }>;
  pillars: Array<{
    pillar_id: PillarId;
    status: EvidencePillar["status"];
    summary: string;
    provenance: string | null;
    freshness: string | null;
    source_family: string | null;
    evidence_mode: EvidenceMode | null;
    blocked_reasons: string[];
  }>;
  trustos: {
    status: ControlPlaneStatus;
    outcome: string | null;
    next_best_action: string | null;
    blocked_reasons: string[];
    public_launch_decision?: string | null;
  };
  governor: {
    status: ControlPlaneStatus;
    outcome: string | null;
    next_best_action: string | null;
    blocked_reasons: string[];
  };
  approval_ledger: {
    status: ControlPlaneStatus;
    outcome: string | null;
    next_best_action: string | null;
    blocked_reasons: string[];
  };
  fingerprint: {
    read_only: boolean;
    network_calls: boolean;
    source_labels: string[];
    source_families: string[];
    report_version: string | null;
    generated_at: string | null;
  };
  warnings: string[];
  blocked_reasons: string[];
  unavailable_reasons?: string[];
  read_only: true;
  mutated: false;
  network_calls: boolean;
  /** Optional PR #247 research-to-decision appendix; overlay only, never a second ranking. */
  appendix?: {
    candidate_audit?: Array<{
      candidate_id?: string;
      sku?: string | null;
      supplier_sku?: string | null;
      lifecycle_state?: string | null;
      lane?: {
        origin?: string | null;
        destination?: string | null;
        currency?: string | null;
      } | null;
      assumptions?: string[];
      missing_evidence?: string[];
      conflicts?: string[];
      confidence?: {
        supplier?: number;
        marketplace?: number;
        overall?: number;
      } | null;
      supplier_offer?: string | null;
    }>;
  };
}
