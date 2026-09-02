/** Read-only first-phase evidence cockpit contract (frontend view model). */

export type EvidenceState =
  | "loading"
  | "empty"
  | "blocked"
  | "unavailable"
  | "stale"
  | "success";

export type EvidenceMode =
  | "fixture_only"
  | "manual"
  | "simulated"
  | "live_readonly"
  | "unknown";

export type ControlPlaneStatus = "unavailable" | "fixture" | "live_readonly";

export interface RankedCandidateRow {
  candidateId: string;
  title: string;
  rankIndex: number;
  evidenceCompleteness: number | null;
  supplierScore: number | null;
  competitionScore: number | null;
  economicsLabel: string | null;
  commercialDecision: string | null;
  nextBestAction: string | null;
  riskLevel: string | null;
  isTopCandidate: boolean;
}

export interface EvidencePillar {
  id:
    | "market_evidence"
    | "consumer_attention"
    | "supplier_feasibility"
    | "economics"
    | "provenance"
    | "freshness";
  label: string;
  status: "available" | "partial" | "unavailable" | "blocked";
  summary: string;
  provenance: string | null;
  freshness: string | null;
  blockedReasons: string[];
}

export interface ControlPlaneSlot {
  id: "trustos" | "governor" | "approval_ledger";
  label: string;
  status: ControlPlaneStatus;
  outcome: string | null;
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

/** Future backend contract (not merged): GET /api/phase1/evidence-cockpit */
export interface FirstPhaseEvidenceCockpitApiContract {
  report_version: string;
  generated_at: string;
  evidence_mode: EvidenceMode;
  overall_status: string;
  ranked_candidates: Array<{
    candidate_id: string;
    title: string;
    rank_index: number;
    evidence_completeness: number;
    supplier_score: number;
    competition_score: number;
    economics_label: string;
    commercial_decision: string;
    next_best_action: string;
    risk_level: string;
    is_top_candidate: boolean;
  }>;
  pillars: Array<{
    pillar_id: EvidencePillar["id"];
    status: EvidencePillar["status"];
    summary: string;
    provenance: string | null;
    freshness: string | null;
    blocked_reasons: string[];
  }>;
  trustos: {
    status: ControlPlaneStatus;
    outcome: string | null;
    blocked_reasons: string[];
  };
  governor: {
    status: ControlPlaneStatus;
    outcome: string | null;
    blocked_reasons: string[];
  };
  approval_ledger: {
    status: ControlPlaneStatus;
    outcome: string | null;
    blocked_reasons: string[];
  };
  fingerprint: {
    read_only: boolean;
    network_calls: boolean;
    source_labels: string[];
  };
  warnings: string[];
  blocked_reasons: string[];
  read_only: true;
  mutated: false;
  network_calls: boolean;
}
