import {
  PRODUCT_VALIDATION_REPORT_VERSION,
  RESEARCH_TO_DECISION_APPENDIX_VERSION,
  type EvidenceClass,
  type RankedCandidateRow,
} from "../contracts/firstPhaseEvidencePacket";
import { classifyEvidenceClass } from "./classifyEvidence";
import { derivePromotionState } from "./derivePromotionState";
import { containsSecretShapedValue } from "./exportClientSafeReport";
import { formatFreshnessLabel, isStaleFreshness } from "./freshness";

export type ProjectionValidationResult =
  | { ok: true; packet: ResearchToDecisionProjection }
  | { ok: false; reason: string };

export interface ResearchToDecisionAuditRow {
  candidate_id?: string;
  sku?: string | null;
  supplier_sku?: string | null;
  title?: string;
  lifecycle_state?: string | null;
  evidence_expiry?: string | null;
  lane?: {
    origin?: string | null;
    origin_country?: string | null;
    destination?: string | null;
    destination_country?: string | null;
    currency?: string | null;
    warehouse?: string | null;
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
  supplier_offers?: Array<{
    offer_id?: string;
    exact_sku?: string | null;
    status?: string | null;
    issues?: string[];
  }>;
  economics?: Record<string, unknown> | null;
  observed_values?: {
    marketplace_evidence_count?: number;
    supplier_offer_count?: number;
  } | null;
  decision?: string | null;
  next_action?: string | null;
  hard_gates?: string[];
}

export interface ResearchToDecisionProjection {
  report_version: typeof PRODUCT_VALIDATION_REPORT_VERSION;
  appendix: {
    research_to_decision_version: typeof RESEARCH_TO_DECISION_APPENDIX_VERSION;
    replay_fingerprint?: string | null;
    market_lane?: ResearchToDecisionAuditRow["lane"];
    source_authorities?: Record<string, string>;
    candidate_audit?: ResearchToDecisionAuditRow[];
  };
  executive_summary?: {
    consumer_attention_signals?: { status?: string | null };
    marketplace_demand_signals?: { status?: string | null };
    supplier_feasibility_signals?: { status?: string | null };
  };
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

/** Fail-closed schema gate for the existing product-validation-report projection. */
export function validateResearchToDecisionProjection(raw: unknown): ProjectionValidationResult {
  if (!raw || typeof raw !== "object") return { ok: false, reason: "projection_not_object" };
  if (containsSecretShapedValue(raw)) return { ok: false, reason: "secret_shaped_value_rejected" };
  const packet = raw as Record<string, unknown>;
  const reportVersion = packet.report_version;
  if (reportVersion !== PRODUCT_VALIDATION_REPORT_VERSION) {
    return { ok: false, reason: "schema_version_unsupported" };
  }
  const appendix = asRecord(packet.appendix);
  if (!appendix) return { ok: false, reason: "appendix_required" };
  if (appendix.research_to_decision_version !== RESEARCH_TO_DECISION_APPENDIX_VERSION) {
    return { ok: false, reason: "schema_version_unsupported" };
  }
  if (appendix.candidate_audit !== undefined && !Array.isArray(appendix.candidate_audit)) {
    return { ok: false, reason: "candidate_audit_malformed" };
  }
  const replay = appendix.replay_fingerprint;
  if (replay != null && (typeof replay !== "string" || !/^[a-f0-9]{64}$/i.test(replay))) {
    return { ok: false, reason: "replay_identity_invalid" };
  }
  return { ok: true, packet: packet as unknown as ResearchToDecisionProjection };
}

function firstAcceptedSku(audit: ResearchToDecisionAuditRow): string | null {
  const offers = audit.supplier_offers ?? [];
  for (const offer of offers) {
    if (offer.status === "quarantined") continue;
    if (typeof offer.exact_sku === "string" && offer.exact_sku) return offer.exact_sku;
  }
  if (typeof audit.sku === "string" && audit.sku) return audit.sku;
  return null;
}

function summarizeOffer(audit: ResearchToDecisionAuditRow): string | null {
  if (typeof audit.supplier_offer === "string" && audit.supplier_offer) return audit.supplier_offer;
  const offers = audit.supplier_offers ?? [];
  const accepted = offers.find((offer) => offer.status !== "quarantined" && offer.offer_id);
  if (!accepted) return null;
  const sku = accepted.exact_sku ? ` sku ${accepted.exact_sku}` : "";
  return `${accepted.offer_id}${sku}`;
}

function economicsUnavailable(economics: Record<string, unknown> | null | undefined): boolean {
  if (!economics) return true;
  return Object.keys(economics).length === 0;
}

function economicsLabel(economics: Record<string, unknown> | null | undefined): string | null {
  if (economicsUnavailable(economics)) return null;
  const margin = economics?.gross_margin_percent;
  if (typeof margin === "number") return `gross_margin_percent_${margin}`;
  const quality = economics?.margin_quality;
  if (typeof quality === "string" && quality) return quality;
  return null;
}

function mapLane(
  audit: ResearchToDecisionAuditRow,
  packetLane: ResearchToDecisionAuditRow["lane"],
): RankedCandidateRow["marketLane"] {
  const lane = audit.lane ?? packetLane;
  if (!lane) return null;
  const destination = lane.destination_country ?? lane.destination ?? null;
  const origin = lane.origin_country ?? lane.origin ?? null;
  const currency = lane.currency ?? null;
  const warehouse = lane.warehouse ?? null;
  if (!destination && !origin && !currency && !warehouse) return null;
  return { origin, destination, currency, warehouse };
}

function offerConflicts(audit: ResearchToDecisionAuditRow): string[] {
  if (Array.isArray(audit.conflicts)) return [...audit.conflicts];
  const issues = (audit.supplier_offers ?? []).flatMap((offer) => offer.issues ?? []);
  return issues;
}

/**
 * Overlay PR #247 candidate_audit onto existing server-ordered rows.
 * Does not sort, invent ranking, average confidence, or upgrade evidence class.
 * Missing audits and missing fields stay unavailable.
 */
export function overlayResearchToDecisionAudits(
  rows: RankedCandidateRow[],
  audits: ResearchToDecisionAuditRow[] | null | undefined,
  options: {
    replayIdentity?: string | null;
    evidenceReferences?: string[];
    consumerAttentionStatus?: string | null;
    packetLane?: ResearchToDecisionAuditRow["lane"];
    nowMs?: number;
  } = {},
): RankedCandidateRow[] {
  if (!audits?.length) return rows;
  const byId = new Map<string, ResearchToDecisionAuditRow>();
  for (const audit of audits) {
    if (audit.candidate_id) byId.set(audit.candidate_id, audit);
  }
  const refs = options.evidenceReferences ?? [];
  const consumerStatus = options.consumerAttentionStatus ?? null;
  return rows.map((row) => {
    const audit = byId.get(row.candidateId);
    if (!audit) return row;
    const sku = firstAcceptedSku(audit);
    const overall = typeof audit.confidence?.overall === "number" ? audit.confidence.overall : null;
    const supplierConf = typeof audit.confidence?.supplier === "number" ? audit.confidence.supplier : null;
    const marketConf = typeof audit.confidence?.marketplace === "number" ? audit.confidence.marketplace : null;
    const expiry = audit.evidence_expiry ?? null;
    const freshnessLabel = formatFreshnessLabel(expiry, options.nowMs ?? Date.now());
    const stale = isStaleFreshness(freshnessLabel);
    const economicsMissing = economicsUnavailable(audit.economics);
    const mappedEconomics = economicsLabel(audit.economics);
    const decision = audit.decision ?? audit.next_action ?? null;
    const nextAction = audit.next_action ?? audit.decision ?? null;
    const hardGates = Array.isArray(audit.hard_gates) ? [...audit.hard_gates] : [];
    const promotion = derivePromotionState(audit.lifecycle_state ?? decision ?? row.commercialDecision);
    const competitionCount = audit.observed_values?.marketplace_evidence_count;
    const supplierClass: EvidenceClass = classifyEvidenceClass({
      evidenceMode: row.evidenceMode,
      sourceFamily: "supplier_feasibility",
      pillarId: "supplier_feasibility",
    });
    const consumerClass: EvidenceClass = consumerStatus && consumerStatus !== "consumer_attention_not_supplied"
      ? classifyEvidenceClass({
        evidenceMode: row.evidenceMode,
        pillarId: "consumer_attention",
        sourceFamily: "consumer_attention",
      })
      : "not_run";
    const freshnessClass: EvidenceClass = stale ? "stale" : classifyEvidenceClass({
      evidenceMode: row.evidenceMode,
      pillarId: "freshness",
    });
    return {
      ...row,
      productTitle: audit.title ?? row.productTitle ?? row.title,
      sku,
      marketLane: mapLane(audit, options.packetLane) ?? row.marketLane,
      supplierOffer: summarizeOffer(audit),
      assumptions: Array.isArray(audit.assumptions) ? [...audit.assumptions] : row.assumptions,
      missingEvidence: Array.isArray(audit.missing_evidence) ? [...audit.missing_evidence] : row.missingEvidence,
      conflicts: offerConflicts(audit),
      confidence: overall,
      confidenceSupplier: supplierConf,
      confidenceMarketplace: marketConf,
      commercialDecision: decision ?? row.commercialDecision,
      nextBestAction: nextAction ?? row.nextBestAction,
      promotionState: promotion,
      hardGates,
      evidenceReferences: refs.length ? refs : row.evidenceReferences,
      consumerAttentionSummary: consumerStatus,
      competitionSummary: typeof competitionCount === "number"
        ? `marketplace_evidence_count_${competitionCount}`
        : null,
      replayIdentity: options.replayIdentity ?? row.replayIdentity,
      freshnessExpiry: expiry,
      supplierEvidenceClass: supplierClass,
      consumerEvidenceClass: consumerClass,
      economicsUnavailable: economicsMissing,
      economicsLabel: economicsMissing ? null : (mappedEconomics ?? row.economicsLabel),
      pillarCells: row.pillarCells.map((cell) => {
        if (cell.pillarId === "consumer_attention") {
          return { ...cell, evidenceClass: consumerClass, status: consumerClass === "not_run" ? "unavailable" : cell.status };
        }
        if (cell.pillarId === "supplier_feasibility") {
          return { ...cell, evidenceClass: supplierClass };
        }
        if (cell.pillarId === "economics" && economicsMissing) {
          return { ...cell, status: "unavailable", detail: "economics_unavailable", evidenceClass: "unavailable" };
        }
        if (cell.pillarId === "freshness") {
          return {
            ...cell,
            evidenceClass: freshnessClass,
            status: stale ? "partial" : cell.status,
            detail: freshnessLabel ?? cell.detail,
          };
        }
        return cell;
      }),
    };
  });
}

export function overlayResearchToDecisionProjection(
  rows: RankedCandidateRow[],
  raw: unknown,
  nowMs: number = Date.now(),
): { rows: RankedCandidateRow[]; warning: string | null; replayIdentity: string | null } {
  const validated = validateResearchToDecisionProjection(raw);
  if (!validated.ok) {
    return { rows, warning: validated.reason, replayIdentity: null };
  }
  const appendix = validated.packet.appendix;
  const authorities = appendix.source_authorities ?? {};
  const refs = Object.values(authorities).filter((value) => typeof value === "string");
  const consumerStatus = validated.packet.executive_summary?.consumer_attention_signals?.status ?? null;
  return {
    rows: overlayResearchToDecisionAudits(rows, appendix.candidate_audit, {
      replayIdentity: appendix.replay_fingerprint ?? null,
      evidenceReferences: refs,
      consumerAttentionStatus: consumerStatus,
      packetLane: appendix.market_lane,
      nowMs,
    }),
    warning: null,
    replayIdentity: appendix.replay_fingerprint ?? null,
  };
}
