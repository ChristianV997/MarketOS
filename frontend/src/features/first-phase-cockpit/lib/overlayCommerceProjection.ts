import { MAX_PROJECTION_CANDIDATES, type RankedCandidateRow } from "../contracts/firstPhaseEvidencePacket.ts";
import { containsSecretShapedValue } from "./exportClientSafeReport.ts";
import { derivePromotionState } from "./derivePromotionState.ts";
import { enrichDecisionReview } from "./mapDecisionReview.ts";

export const COMMERCE_CLIENT_PROJECTION_SCHEMA = "MarketOS.ClientCommerceProjection.v1";

export type CommerceAdapterResult = {
  rows: RankedCandidateRow[];
  warning: string | null;
  accepted: boolean;
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

/**
 * Overlay a sanitized #250 client commerce projection by candidate_id.
 * Does not copy the backend promotion state machine or recalculate economics.
 */
export function adaptCommerceProjection(
  rows: RankedCandidateRow[],
  raw: unknown,
  operatorWorkspaceId: string | null = null,
): CommerceAdapterResult {
  if (raw == null) {
    return { rows, warning: "commerce_client_projection_unavailable", accepted: false };
  }
  if (containsSecretShapedValue(raw)) {
    return { rows, warning: "secret_shaped_value_rejected", accepted: false };
  }
  const packet = asRecord(raw);
  if (!packet) return { rows, warning: "projection_not_object", accepted: false };
  const schema = String(packet.schema ?? packet.schema_version ?? "");
  if (schema && schema !== COMMERCE_CLIENT_PROJECTION_SCHEMA) {
    return { rows, warning: "schema_version_unsupported", accepted: false };
  }
  if (!schema) return { rows, warning: "schema_version_unsupported", accepted: false };
  if (packet.launch_authorized === true) {
    return { rows, warning: "launch_authorized_rejected", accepted: false };
  }
  const candidates = packet.candidates;
  if (candidates !== undefined && !Array.isArray(candidates)) {
    return { rows, warning: "commerce_candidates_malformed", accepted: false };
  }
  const list = Array.isArray(candidates) ? candidates : [];
  if (list.length > MAX_PROJECTION_CANDIDATES) {
    return { rows, warning: "projection_oversized", accepted: false };
  }
  const byId = new Map<string, Record<string, unknown>>();
  for (const item of list) {
    const record = asRecord(item);
    if (!record || typeof record.candidate_id !== "string" || !record.candidate_id.trim()) {
      return { rows, warning: "candidate_identity_missing", accepted: false };
    }
    if (byId.has(record.candidate_id)) {
      return { rows, warning: "candidate_identity_duplicate", accepted: false };
    }
    const workspace = record.workspace_id == null ? null : String(record.workspace_id);
    if (operatorWorkspaceId && workspace && workspace !== operatorWorkspaceId) {
      return { rows, warning: "cross_workspace_rejected", accepted: false };
    }
    byId.set(record.candidate_id, record);
  }

  const next = rows.map((row) => {
    const overlay = byId.get(row.candidateId);
    if (!overlay) return row;
    const sku = typeof overlay.supplier_sku === "string" ? overlay.supplier_sku : row.sku;
    const offerId = typeof overlay.offer_id === "string" ? overlay.offer_id : null;
    const blockers = Array.isArray(overlay.blockers) ? overlay.blockers.map((item) => String(item)) : row.hardGates;
    const missing = Array.isArray(overlay.missing_evidence)
      ? overlay.missing_evidence.map((item) => String(item))
      : row.missingEvidence;
    const decision = typeof overlay.decision === "string" ? overlay.decision : row.commercialDecision;
    const transitions = Array.isArray(overlay.promotion_transitions)
      ? overlay.promotion_transitions.map((item) => {
        const record = asRecord(item) ?? {};
        return {
          from: record.from == null ? null : String(record.from),
          to: record.to == null ? null : String(record.to),
          status: "observed" as const,
          reason: record.reason == null ? null : String(record.reason),
        };
      })
      : row.promotionTransitions;
    return enrichDecisionReview({
      ...row,
      sku: sku ?? row.sku,
      supplierOffer: offerId ?? row.supplierOffer,
      offerDisposition: typeof overlay.offer_status === "string"
        ? (overlay.offer_status === "quarantined" ? "quarantined" : "accepted")
        : row.offerDisposition,
      hardGates: blockers,
      missingEvidence: missing,
      commercialDecision: decision,
      nextBestAction: typeof overlay.next_action === "string" ? overlay.next_action : row.nextBestAction,
      promotionState: derivePromotionState(
        typeof overlay.promotion_state === "string" ? overlay.promotion_state : decision,
      ),
      economicsLabel: typeof overlay.economics_label === "string" ? overlay.economics_label : row.economicsLabel,
      economicsUnavailable: overlay.economics_label == null ? row.economicsUnavailable : false,
      promotionTransitions: transitions,
      conflicts: Array.isArray(overlay.conflicts) ? overlay.conflicts.map((item) => String(item)) : row.conflicts,
    });
  });

  return { rows: next, warning: null, accepted: true };
}
