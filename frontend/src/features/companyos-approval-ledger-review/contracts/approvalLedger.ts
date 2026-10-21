/**
 * Frontend view contract for the existing CompanyOS Approval Ledger report.
 *
 * Source of truth: evaluation.companyos.approval_ledger.ApprovalLedgerReport.to_dict()
 * report_version: companyos-approval-ledger-v1
 *
 * There is no mounted read-only HTTP GET for this ledger on main. This feature
 * consumes the offline CLI artifact contract (mirrored fixture), not a invented API.
 */

export const APPROVAL_LEDGER_REPORT_VERSION = "companyos-approval-ledger-v1" as const;

export const REQUEST_STATUSES = [
  "draft",
  "pending_review",
  "approved",
  "denied",
  "expired",
  "revoked",
  "simulated",
  "blocked_by_policy",
] as const;

export const DECISION_CLASSES = [
  "approval_required",
  "approval_possible_later",
  "blocked_in_current_mode",
  "approved_simulation_only",
] as const;

export type RequestStatus = (typeof REQUEST_STATUSES)[number];
export type DecisionClass = (typeof DECISION_CLASSES)[number];
export type SurfaceState = "loading" | "empty" | "error" | "success";

export interface LedgerEvidenceRef {
  ref_id: string;
  evidence_type: string;
  source: string;
  summary: string;
  sanitized: boolean;
}

export interface LedgerCondition {
  condition_id: string;
  description: string;
  required: boolean;
  satisfied: boolean;
  evidence_ref: string | null;
}

export interface LedgerBudgetCap {
  scope: string;
  per_run: number;
  monthly: number;
  currency: string;
  consumed: number;
  remaining: number;
}

export interface LedgerRequestRow {
  approval_id: string;
  request_type: string;
  request_title: string;
  status: RequestStatus | string;
  risk_level: string;
  required_approver_role: string;
  evidence: LedgerEvidenceRef[];
  conditions: LedgerCondition[];
  status_bucket: "blocked" | "pending" | "simulated" | "draft" | "approved_record" | "closed" | "other";
}

export interface LedgerPolicyRow {
  policy_id: string;
  request_type: string;
  decision_class: DecisionClass | string;
  default_risk: string;
  required_approver_role: string;
  rationale: string;
  blocked_in_current_mode: boolean;
  budget_cap: LedgerBudgetCap | null;
}

export interface LedgerSimulationRow {
  simulation_id: string;
  action: string;
  request_type: string;
  result: string;
  can_be_approved_now: boolean;
  missing_conditions: string[];
  blocking_reasons: string[];
}

export interface LedgerSafetySummary {
  read_only: boolean;
  network_calls: boolean;
  mutated: boolean;
  external_action_performed: boolean;
  credentials_present: boolean;
  live_capabilities_enabled: boolean;
  policy_fail_closed: boolean;
  audit_trail_present: boolean;
  secrets_stored: boolean;
  summary: string;
}

export interface LedgerQueueSummary {
  pending: number;
  approved: number;
  denied: number;
  expired: number;
  revoked: number;
  blocked: number;
  draft_or_simulated: number;
  high_risk: number;
  missing_conditions: number;
}

export interface ApprovalLedgerViewModel {
  report_version: string;
  generated_at: string;
  approval_count: number;
  pending_count: number;
  approved_count: number;
  blocked_count: number;
  denied_count: number;
  expired_count: number;
  revoked_count: number;
  critical_count: number;
  next_best_action: string;
  queue_summary: LedgerQueueSummary;
  safety_summary: LedgerSafetySummary;
  requests: LedgerRequestRow[];
  policies: LedgerPolicyRow[];
  simulations: LedgerSimulationRow[];
  audit_event_count: number;
  /** Always false for this offline ledger surface. */
  execution_authorized: false;
  /** Always true: scorecards/drafts never authorize execution here. */
  offline_planning_only: true;
  /** demo fixture vs operator-selected local JSON vs rejected/unavailable. */
  availability: "fixture" | "local_import" | "unavailable";
  limitations: string[];
}

export type ApprovalLedgerReportSource = "demo_fixture" | "local_file";
