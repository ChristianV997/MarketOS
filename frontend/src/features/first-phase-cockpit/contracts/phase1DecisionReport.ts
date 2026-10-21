/**
 * Page-local view model for GET /api/phase1/readiness.
 * Fields mirror the existing readiness JSON on main — nothing invented.
 */

export type DecisionReportState = "loading" | "empty" | "error" | "success";

export type EvidenceAuthorityKind =
  | "live_supplier_proof"
  | "structural_ready"
  | "fixture_or_manual"
  | "partial_or_degraded"
  | "unavailable"
  | "blocked";

export interface DecisionCategoryRow {
  key: string;
  label: string;
  status: string;
  authority: EvidenceAuthorityKind;
  detail: string;
  points: number | null;
  weight: number | null;
}

export interface Phase1DecisionReportView {
  state: DecisionReportState;
  overallStatus: string | null;
  overallScore: number | null;
  nextBestAction: string | null;
  nextBestPromptHint: string | null;
  blockingGates: string[];
  advisoryWarnings: string[];
  allowedNextPhases: string[];
  forbiddenNextPhases: string[];
  assumptionPercentage: number | null;
  assumptionLabels: string[];
  evidenceSummaryLines: string[];
  provenanceLines: string[];
  categories: DecisionCategoryRow[];
  supplierIsLiveProof: boolean;
  competitionIsLiveObserved: boolean;
  readOnly: boolean;
  networkCalls: boolean;
  mutated: boolean;
  errorMessage: string | null;
  emptyMessage: string | null;
}
