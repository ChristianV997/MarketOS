import type { RankedCandidateRow } from "../contracts/firstPhaseEvidencePacket";
import { derivePromotionState } from "./derivePromotionState";

/**
 * Overlay PR #247 research-to-decision appendix.candidate_audit onto existing
 * server-ordered rows. Does not sort, invent ranking, or treat the overlay as
 * a live API. Missing audits leave rows unchanged.
 */
export interface ResearchToDecisionAuditRow {
  candidate_id?: string;
  sku?: string | null;
  supplier_sku?: string | null;
  title?: string;
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
}

export function overlayResearchToDecisionAudits(
  rows: RankedCandidateRow[],
  audits: ResearchToDecisionAuditRow[] | null | undefined,
): RankedCandidateRow[] {
  if (!audits?.length) return rows;
  const byId = new Map<string, ResearchToDecisionAuditRow>();
  for (const audit of audits) {
    if (audit.candidate_id) byId.set(audit.candidate_id, audit);
  }
  return rows.map((row) => {
    const audit = byId.get(row.candidateId);
    if (!audit) return row;
    const supplier = audit.confidence?.supplier;
    const market = audit.confidence?.marketplace;
    const overall = audit.confidence?.overall
      ?? (typeof supplier === "number" && typeof market === "number"
        ? (supplier + market) / 2
        : supplier ?? market ?? row.confidence);
    return {
      ...row,
      sku: audit.sku ?? audit.supplier_sku ?? row.sku,
      marketLane: audit.lane
        ? {
            origin: audit.lane.origin ?? row.marketLane?.origin ?? null,
            destination: audit.lane.destination ?? row.marketLane?.destination ?? null,
            currency: audit.lane.currency ?? row.marketLane?.currency ?? null,
          }
        : row.marketLane,
      supplierOffer: audit.supplier_offer ?? row.supplierOffer,
      assumptions: audit.assumptions ?? row.assumptions,
      missingEvidence: audit.missing_evidence ?? row.missingEvidence,
      conflicts: audit.conflicts ?? row.conflicts,
      confidence: overall ?? row.confidence,
      promotionState: derivePromotionState(audit.lifecycle_state ?? row.commercialDecision),
    };
  });
}
