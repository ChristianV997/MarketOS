import {
  CLIENT_SAFE_SERVICE_EXPORT_VERSION,
  type ClientSafeServiceExport,
  type ServiceEngagement,
} from "../contracts/serviceEngagementProjection.ts";

const SECRET_SHAPED = /sk-live-|sk-test-|ghp_|github_pat_|AKIA[0-9A-Z]{16}|bearer\s+[a-z0-9._-]{10,}/i;
const FORBIDDEN_KEY = /(prompt|formula|heuristic|source_code|private_key|provider_payload|internal_notes|private_note|credential|cross_client|cross_workspace)/i;
const PATH_SHAPED = /(^|[\\/])(users|home|documents|marketos)[\\/]/i;
const HTML_SHAPED = /<\/?[a-z][\s\S]*>/i;
const FORMULA_SHAPED = /\b(?:contribution|fee|labor|tooling)\s*=\s*/i;

export const EXPORT_OMIT_KEYS = [
  "internal_prompt",
  "internal_formula",
  "private_operator_notes",
  "source_code",
  "credentials",
  "raw_provider_payload",
  "cross_client_data",
  "hidden_heuristics",
] as const;

export function containsSecretShapedValue(value: unknown): boolean {
  if (typeof value === "string") {
    return SECRET_SHAPED.test(value) || PATH_SHAPED.test(value) || HTML_SHAPED.test(value) || FORMULA_SHAPED.test(value);
  }
  if (Array.isArray(value)) return value.some(containsSecretShapedValue);
  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>).some(([key, item]) => {
      if (FORBIDDEN_KEY.test(key)) return true;
      return containsSecretShapedValue(item);
    });
  }
  return false;
}

export function buildClientSafeServiceExport(engagement: ServiceEngagement): ClientSafeServiceExport {
  if (containsSecretShapedValue({
    id: engagement.engagement_id,
    client: engagement.intake.display_name,
    evidence: engagement.evidence,
    deliverables: engagement.deliverables,
    nba: engagement.next_best_action,
  })) {
    return {
      export_version: CLIENT_SAFE_SERVICE_EXPORT_VERSION,
      accepted: false,
      rejection_reason: "Export rejected: secret-shaped or credential-like value in client-visible fields.",
      read_only: true,
      mutated: false,
      payload: null,
    };
  }

  if (engagement.eligibility.data_inadequate || engagement.lifecycle_state === "data_inadequate") {
    const missing = engagement.eligibility.required_from_client;
    const missingLabel = missing.length
      ? missing.map((item) => `${item.field} (${item.how_to_provide})`).join("; ")
      : engagement.missing_data.join("; ") || "unspecified client intake";
    return {
      export_version: CLIENT_SAFE_SERVICE_EXPORT_VERSION,
      accepted: false,
      rejection_reason:
        `Export rejected: data_inadequate. Missing client input: ${missingLabel}. This is not a complete deliverable.`,
      read_only: true,
      mutated: false,
      payload: {
        engagement_id: engagement.engagement_id,
        lifecycle_state: engagement.lifecycle_state,
        required_from_client: missing,
        missing_data: engagement.missing_data,
      },
    };
  }

  const payload = {
    engagement_id: engagement.engagement_id,
    client_display_name: engagement.intake.display_name,
    service_id: engagement.service_id,
    lifecycle_state: engagement.lifecycle_state,
    evidence: engagement.evidence.map((item) => ({
      title: item.title,
      evidence_class: item.evidence_class,
      summary: item.summary,
    })),
    deliverables: engagement.deliverables.map((item) => ({
      name: item.name,
      status: item.status,
    })),
    missing_data: engagement.missing_data,
    assumptions: engagement.assumptions,
    next_best_action: engagement.next_best_action.action,
    economics: {
      fee: engagement.economics.fee,
      contribution: engagement.economics.contribution,
      note: engagement.economics.planning_assumption_note,
      frontend_calculates: false,
    },
    creative_assets: engagement.creative_assets.map((item) => ({
      skill_id: item.skill_id,
      status: item.status,
      generation_enabled: false,
    })),
    omitted: [...EXPORT_OMIT_KEYS],
  };

  if (containsSecretShapedValue(payload)) {
    return {
      export_version: CLIENT_SAFE_SERVICE_EXPORT_VERSION,
      accepted: false,
      rejection_reason: "Export rejected after sanitization still contained a forbidden pattern.",
      read_only: true,
      mutated: false,
      payload: null,
    };
  }

  return {
    export_version: CLIENT_SAFE_SERVICE_EXPORT_VERSION,
    accepted: true,
    rejection_reason: null,
    read_only: true,
    mutated: false,
    payload,
  };
}
