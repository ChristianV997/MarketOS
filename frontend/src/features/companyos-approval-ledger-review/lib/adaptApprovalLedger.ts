import {
  APPROVAL_LEDGER_REPORT_VERSION,
  DECISION_CLASSES,
  REQUEST_STATUSES,
  type ApprovalLedgerViewModel,
  type LedgerBudgetCap,
  type LedgerCondition,
  type LedgerEvidenceRef,
  type LedgerPolicyRow,
  type LedgerQueueSummary,
  type LedgerRequestRow,
  type LedgerSafetySummary,
  type LedgerSimulationRow,
} from "../contracts/approvalLedger.ts";
import { safeDisplayText } from "./safeText.ts";

const SECRET_KEY = /(password|secret|token|api[_-]?key|apikey|private[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|authorization|cookie|raw[_-]?payload|raw[_-]?html)/i;
const SECRET_VALUE = /sk-live-|sk-test-|ghp_|github_pat_|AKIA[0-9A-Z]{16}|bearer\s+[a-z0-9._-]{10,}|-----begin |xoxb-|aiza/i;
const LEAK = /(cross[ _-]?client|cross[ _-]?workspace|another[ _-]?client|internal[ _-]?prompt|internal[ _-]?formula)/i;
/** Boolean safety flags from the ledger contract that mention "secret" by name. */
const ALLOWED_META_KEYS = new Set(["secrets_stored"]);
const STATUS_SET = new Set<string>(REQUEST_STATUSES);
const CLASS_SET = new Set<string>(DECISION_CLASSES);

export interface AdaptResult {
  rejected: boolean;
  reason: string | null;
  model: ApprovalLedgerViewModel;
}

function record(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function leaky(value: unknown): boolean {
  if (typeof value === "string") return SECRET_VALUE.test(value) || LEAK.test(value);
  if (Array.isArray(value)) return value.some(leaky);
  if (!value || typeof value !== "object") return false;
  return Object.entries(value as Record<string, unknown>).some(([key, item]) => {
    const normalized = key.toLowerCase().replace(/-/g, "_");
    if (!ALLOWED_META_KEYS.has(normalized) && (SECRET_KEY.test(key) || LEAK.test(key))) return true;
    return leaky(item);
  });
}

function num(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function strings(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => safeDisplayText(item, 240)).filter(Boolean);
}

function statusBucket(status: string): LedgerRequestRow["status_bucket"] {
  if (status === "blocked_by_policy") return "blocked";
  if (status === "pending_review") return "pending";
  if (status === "simulated") return "simulated";
  if (status === "draft") return "draft";
  if (status === "approved") return "approved_record";
  if (status === "denied" || status === "expired" || status === "revoked") return "closed";
  return "other";
}

function budget(raw: unknown): LedgerBudgetCap | null {
  const item = record(raw);
  if (!item) return null;
  return {
    scope: safeDisplayText(item.scope, 80) || "unscoped",
    per_run: num(item.per_run),
    monthly: num(item.monthly),
    currency: safeDisplayText(item.currency, 12) || "USD",
    consumed: num(item.consumed),
    remaining: num(item.remaining),
  };
}

function evidence(raw: unknown, index: number): LedgerEvidenceRef | null {
  const item = record(raw);
  if (!item) return null;
  const sanitized = item.sanitized === true;
  if (!sanitized) return null;
  return {
    ref_id: safeDisplayText(item.ref_id ?? `evidence-${index}`, 80) || `evidence-${index}`,
    evidence_type: safeDisplayText(item.evidence_type, 80) || "unspecified",
    source: safeDisplayText(item.source, 120) || "unspecified",
    summary: safeDisplayText(item.summary, 400),
    sanitized: true,
  };
}

function condition(raw: unknown, index: number): LedgerCondition | null {
  const item = record(raw);
  if (!item) return null;
  return {
    condition_id: safeDisplayText(item.condition_id ?? `condition-${index}`, 80) || `condition-${index}`,
    description: safeDisplayText(item.description, 240),
    required: item.required === true,
    satisfied: item.satisfied === true,
    evidence_ref: item.evidence_ref == null || String(item.evidence_ref).trim() === ""
      ? null
      : safeDisplayText(item.evidence_ref, 80),
  };
}

function empty(reason: string): ApprovalLedgerViewModel {
  return {
    report_version: APPROVAL_LEDGER_REPORT_VERSION,
    generated_at: "unavailable",
    approval_count: 0,
    pending_count: 0,
    approved_count: 0,
    blocked_count: 0,
    denied_count: 0,
    expired_count: 0,
    revoked_count: 0,
    critical_count: 0,
    next_best_action: "Provide a companyos-approval-ledger-v1 offline report. This page does not invent decisions.",
    queue_summary: {
      pending: 0,
      approved: 0,
      denied: 0,
      expired: 0,
      revoked: 0,
      blocked: 0,
      draft_or_simulated: 0,
      high_risk: 0,
      missing_conditions: 0,
    },
    safety_summary: {
      read_only: true,
      network_calls: false,
      mutated: false,
      external_action_performed: false,
      credentials_present: false,
      live_capabilities_enabled: false,
      policy_fail_closed: true,
      audit_trail_present: false,
      secrets_stored: false,
      summary: reason,
    },
    requests: [],
    policies: [],
    simulations: [],
    audit_event_count: 0,
    execution_authorized: false,
    offline_planning_only: true,
    availability: "unavailable",
    limitations: [reason, "Scorecards and drafts never authorize execution on this surface."],
  };
}

function mapRequest(raw: unknown): LedgerRequestRow | null {
  const item = record(raw);
  if (!item) return null;
  const statusRaw = safeDisplayText(item.status, 40).toLowerCase().replace(/-/g, "_");
  const status = STATUS_SET.has(statusRaw) ? statusRaw : statusRaw || "draft";
  const evidenceRows = Array.isArray(item.evidence)
    ? item.evidence.map(evidence).filter((row): row is LedgerEvidenceRef => row !== null)
    : [];
  const conditions = Array.isArray(item.conditions)
    ? item.conditions.map(condition).filter((row): row is LedgerCondition => row !== null)
    : [];
  return {
    approval_id: safeDisplayText(item.approval_id, 80) || "unknown",
    request_type: safeDisplayText(item.request_type, 80) || "unknown",
    request_title: safeDisplayText(item.request_title, 200) || "Untitled request",
    status,
    risk_level: safeDisplayText(item.risk_level, 40) || "unknown",
    required_approver_role: safeDisplayText(item.required_approver_role, 80) || "human_operator",
    evidence: evidenceRows,
    conditions,
    status_bucket: statusBucket(status),
  };
}

function mapPolicy(raw: unknown): LedgerPolicyRow | null {
  const item = record(raw);
  if (!item) return null;
  const decision = safeDisplayText(item.decision_class, 64).toLowerCase().replace(/-/g, "_");
  return {
    policy_id: safeDisplayText(item.policy_id, 80) || "unknown",
    request_type: safeDisplayText(item.request_type, 80) || "unknown",
    decision_class: CLASS_SET.has(decision) ? decision : decision || "approval_required",
    default_risk: safeDisplayText(item.default_risk, 40) || "unknown",
    required_approver_role: safeDisplayText(item.required_approver_role, 80) || "human_operator",
    rationale: safeDisplayText(item.rationale, 400),
    blocked_in_current_mode: item.blocked_in_current_mode === true,
    budget_cap: budget(item.budget_cap),
  };
}

function mapSimulation(raw: unknown): LedgerSimulationRow | null {
  const item = record(raw);
  if (!item) return null;
  return {
    simulation_id: safeDisplayText(item.simulation_id, 80) || "simulation",
    action: safeDisplayText(item.action, 80) || "unknown",
    request_type: safeDisplayText(item.request_type, 80) || "unknown",
    result: safeDisplayText(item.result, 120) || "unavailable",
    can_be_approved_now: item.can_be_approved_now === true,
    missing_conditions: strings(item.missing_conditions),
    blocking_reasons: strings(item.blocking_reasons),
  };
}

function queue(raw: unknown): LedgerQueueSummary {
  const item = record(raw) ?? {};
  return {
    pending: num(item.pending),
    approved: num(item.approved),
    denied: num(item.denied),
    expired: num(item.expired),
    revoked: num(item.revoked),
    blocked: num(item.blocked),
    draft_or_simulated: num(item.draft_or_simulated),
    high_risk: num(item.high_risk),
    missing_conditions: num(item.missing_conditions),
  };
}

function safety(raw: unknown): LedgerSafetySummary {
  const item = record(raw) ?? {};
  return {
    read_only: item.read_only !== false,
    network_calls: item.network_calls === true,
    mutated: item.mutated === true,
    external_action_performed: item.external_action_performed === true,
    credentials_present: item.credentials_present === true,
    live_capabilities_enabled: item.live_capabilities_enabled === true,
    policy_fail_closed: item.policy_fail_closed !== false,
    audit_trail_present: item.audit_trail_present === true,
    secrets_stored: item.secrets_stored === true,
    summary: safeDisplayText(
      item.summary,
      400,
    ) || "Offline ledger only; records and simulations do not authorize execution.",
  };
}

export function adaptApprovalLedger(raw: unknown): AdaptResult {
  const packet = record(raw);
  if (!packet) return { rejected: true, reason: "malformed", model: empty("Report is not an object.") };
  if (leaky(packet)) return { rejected: true, reason: "prohibited_field", model: empty("Prohibited or secret-shaped field rejected.") };
  if (String(packet.report_version ?? "") !== APPROVAL_LEDGER_REPORT_VERSION) {
    return { rejected: true, reason: "unsupported_version", model: empty("Unsupported Approval Ledger report version.") };
  }

  const safetySummary = safety(packet.safety_summary);
  if (
    !safetySummary.read_only
    || safetySummary.network_calls
    || safetySummary.mutated
    || safetySummary.external_action_performed
    || safetySummary.live_capabilities_enabled
    || safetySummary.credentials_present
    || safetySummary.secrets_stored
  ) {
    return {
      rejected: true,
      reason: "unsafe_safety_summary",
      model: empty("Safety summary claimed live or mutating capability; report rejected."),
    };
  }

  const requests = Array.isArray(packet.requests)
    ? packet.requests.map(mapRequest).filter((row): row is LedgerRequestRow => row !== null)
    : [];
  const policies = Array.isArray(packet.policies)
    ? packet.policies.map(mapPolicy).filter((row): row is LedgerPolicyRow => row !== null)
    : [];
  const simulations = Array.isArray(packet.simulations)
    ? packet.simulations.map(mapSimulation).filter((row): row is LedgerSimulationRow => row !== null)
    : [];

  return {
    rejected: false,
    reason: null,
    model: {
      report_version: APPROVAL_LEDGER_REPORT_VERSION,
      generated_at: safeDisplayText(packet.generated_at, 80) || "offline-deterministic",
      approval_count: num(packet.approval_count, requests.length),
      pending_count: num(packet.pending_count),
      approved_count: num(packet.approved_count),
      blocked_count: num(packet.blocked_count),
      denied_count: num(packet.denied_count),
      expired_count: num(packet.expired_count),
      revoked_count: num(packet.revoked_count),
      critical_count: num(packet.critical_count),
      next_best_action: safeDisplayText(packet.next_best_action, 400)
        || "Review offline policy state. Do not treat this ledger as execution authority.",
      queue_summary: queue(packet.queue_summary),
      safety_summary: safetySummary,
      requests,
      policies,
      simulations,
      audit_event_count: Array.isArray(packet.audit_events) ? packet.audit_events.length : 0,
      execution_authorized: false,
      offline_planning_only: true,
      availability: "fixture",
      limitations: [
        "Offline CompanyOS Approval Ledger artifact. No write, approve, publish, spend, order, or provider action is available here.",
        "A simulated or recorded decision is never live authority.",
        "Scorecards and drafts do not authorize execution.",
      ],
    },
  };
}
