import {
  MAX_PROJECTION_CANDIDATES,
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

export interface ProjectionAdapterResult {
  rows: RankedCandidateRow[];
  warning: string | null;
  accepted: boolean;
  replayIdentity: string | null;
  unmatchedServerIds: string[];
  unmatchedProjectionIds: string[];
}

export interface ResearchToDecisionAuditRow {
  candidate_id?: string;
  sku?: string | null;
  supplier_sku?: string | null;
  title?: string;
  lifecycle_state?: string | null;
  evidence_expiry?: string | null;
  freshness?: string | null;
  risk_state?: string | null;
  evidence_refs?: string[];
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

export interface ClientSafeProjectionCandidate {
  candidate_id?: string;
  title?: string;
  decision?: string | null;
  next_action?: string | null;
  risk_state?: string | null;
  freshness?: string | null;
  confidence?: ResearchToDecisionAuditRow["confidence"];
  missing_evidence?: string[];
  hard_gates?: string[];
  evidence_refs?: string[];
}

export interface ResearchToDecisionProjection {
  report_version: typeof PRODUCT_VALIDATION_REPORT_VERSION;
  appendix: {
    research_to_decision_version: typeof RESEARCH_TO_DECISION_APPENDIX_VERSION;
    replay_fingerprint?: string | null;
    market_lane?: ResearchToDecisionAuditRow["lane"];
    source_authorities?: Record<string, string>;
    candidate_audit?: ResearchToDecisionAuditRow[];
    validation?: {
      network_calls?: boolean;
      read_only?: boolean;
    };
    client_safe_projection?: {
      version?: string;
      network_calls?: boolean;
      launch_authorized?: boolean;
      candidates?: ClientSafeProjectionCandidate[];
    };
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

/** Present finite numbers including 0; missing keys stay unavailable. Never coerce null to 0. */
export function optionalNumber(record: Record<string, unknown> | null | undefined, key: string): number | null {
  if (!record || !(key in record)) return null;
  const value = record[key];
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return value;
}

function indexUniqueAudits(
  audits: Array<{ candidate_id?: string }>,
): { ok: true; byId: Map<string, (typeof audits)[number]> } | { ok: false; reason: string } {
  const byId = new Map<string, (typeof audits)[number]>();
  for (const audit of audits) {
    if (!audit || typeof audit !== "object" || typeof audit.candidate_id !== "string" || !audit.candidate_id) {
      continue;
    }
    if (byId.has(audit.candidate_id)) {
      return { ok: false, reason: "candidate_identity_duplicate" };
    }
    byId.set(audit.candidate_id, audit);
  }
  return { ok: true, byId };
}

/** Fail-closed schema gate for the existing product-validation-report projection. Extra fields are ignored. */
export function validateResearchToDecisionProjection(raw: unknown): ProjectionValidationResult {
  if (!raw || typeof raw !== "object") return { ok: false, reason: "projection_not_object" };
  if (containsSecretShapedValue(raw)) return { ok: false, reason: "secret_shaped_value_rejected" };
  const packet = raw as Record<string, unknown>;
  if (packet.report_version !== PRODUCT_VALIDATION_REPORT_VERSION) {
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
  const clientSafe = asRecord(appendix.client_safe_projection);
  if (clientSafe?.launch_authorized === true) {
    return { ok: false, reason: "launch_authorized_rejected" };
  }
  if (clientSafe?.candidates !== undefined && !Array.isArray(clientSafe.candidates)) {
    return { ok: false, reason: "client_safe_projection_malformed" };
  }
  const auditCount = Array.isArray(appendix.candidate_audit) ? appendix.candidate_audit.length : 0;
  const safeCount = Array.isArray(clientSafe?.candidates) ? clientSafe.candidates.length : 0;
  if (auditCount > MAX_PROJECTION_CANDIDATES || safeCount > MAX_PROJECTION_CANDIDATES) {
    return { ok: false, reason: "projection_oversized" };
  }
  const replay = appendix.replay_fingerprint;
  if (replay != null && (typeof replay !== "string" || !/^[a-f0-9]{64}$/i.test(replay))) {
    return { ok: false, reason: "replay_identity_invalid" };
  }
  if (Array.isArray(appendix.candidate_audit)) {
    const indexed = indexUniqueAudits(appendix.candidate_audit as Array<{ candidate_id?: string }>);
    if (!indexed.ok) return indexed;
  }
  if (Array.isArray(clientSafe?.candidates)) {
    const indexed = indexUniqueAudits(clientSafe.candidates as Array<{ candidate_id?: string }>);
    if (!indexed.ok) return indexed;
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
  const margin = optionalNumber(economics ?? undefined, "gross_margin_percent");
  if (margin !== null) return `gross_margin_percent_${margin}`;
  const quality = economics?.margin_quality;
  if (typeof quality === "string" && quality) return quality;
  return null;
}

function mapLane(
  audit: ResearchToDecisionAuditRow | undefined,
  packetLane: ResearchToDecisionAuditRow["lane"],
): RankedCandidateRow["marketLane"] {
  const lane = audit?.lane ?? packetLane;
  if (!lane) return null;
  const destination = lane.destination_country ?? lane.destination ?? null;
  const origin = lane.origin_country ?? lane.origin ?? null;
  const currency = lane.currency ?? null;
  const warehouse = lane.warehouse ?? null;
  if (!destination && !origin && !currency && !warehouse) return null;
  return { origin, destination, currency, warehouse };
}

function mergeAudit(
  audit: ResearchToDecisionAuditRow | undefined,
  safe: ClientSafeProjectionCandidate | undefined,
): ResearchToDecisionAuditRow | undefined {
  if (!audit && !safe) return undefined;
  return {
    ...(safe ?? {}),
    ...(audit ?? {}),
    candidate_id: audit?.candidate_id ?? safe?.candidate_id,
    title: audit?.title ?? safe?.title,
    decision: audit?.decision ?? safe?.decision,
    next_action: audit?.next_action ?? safe?.next_action,
    risk_state: audit?.risk_state ?? safe?.risk_state,
    freshness: audit?.freshness ?? safe?.freshness,
    confidence: audit?.confidence ?? safe?.confidence,
    missing_evidence: audit?.missing_evidence ?? safe?.missing_evidence,
    hard_gates: audit?.hard_gates ?? safe?.hard_gates,
    evidence_refs: audit?.evidence_refs ?? safe?.evidence_refs,
  };
}

/**
 * Overlay existing #247 candidate_audit / client_safe_projection onto server-ordered rows.
 * Does not sort, invent ranking, average confidence, coerce unavailable to zero, or
 * upgrade fixture/manual evidence to live proof. Report-only IDs stay unmatched.
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
    clientSafeCandidates?: ClientSafeProjectionCandidate[];
  } = {},
): { rows: RankedCandidateRow[]; unmatchedServerIds: string[]; unmatchedProjectionIds: string[]; warning: string | null } {
  if (!audits?.length && !options.clientSafeCandidates?.length) {
    return { rows, unmatchedServerIds: [], unmatchedProjectionIds: [], warning: null };
  }
  const auditIndex = indexUniqueAudits(audits ?? []);
  if (!auditIndex.ok) return { rows, unmatchedServerIds: [], unmatchedProjectionIds: [], warning: auditIndex.reason };
  const safeIndex = indexUniqueAudits(options.clientSafeCandidates ?? []);
  if (!safeIndex.ok) return { rows, unmatchedServerIds: [], unmatchedProjectionIds: [], warning: safeIndex.reason };

  const projectionIds = new Set<string>([...auditIndex.byId.keys(), ...safeIndex.byId.keys()]);
  const unmatchedServerIds: string[] = [];
  const matched = new Set<string>();
  const refs = options.evidenceReferences ?? [];
  const consumerStatus = options.consumerAttentionStatus ?? null;

  const nextRows = rows.map((row) => {
    const audit = mergeAudit(
      auditIndex.byId.get(row.candidateId) as ResearchToDecisionAuditRow | undefined,
      safeIndex.byId.get(row.candidateId) as ClientSafeProjectionCandidate | undefined,
    );
    if (!audit) {
      unmatchedServerIds.push(row.candidateId);
      return row;
    }
    matched.add(row.candidateId);
    const sku = firstAcceptedSku(audit);
    const confidenceRecord = audit.confidence as Record<string, unknown> | null | undefined;
    const overall = optionalNumber(confidenceRecord, "overall");
    const supplierConf = optionalNumber(confidenceRecord, "supplier");
    const marketConf = optionalNumber(confidenceRecord, "marketplace");
    const expiry = audit.evidence_expiry ?? null;
    const freshnessLabel = formatFreshnessLabel(expiry, options.nowMs ?? Date.now());
    const declaredFreshness = (audit.freshness ?? "").toLowerCase();
    const stale = declaredFreshness === "expired" || isStaleFreshness(freshnessLabel);
    const economicsMissing = economicsUnavailable(audit.economics);
    const mappedEconomics = economicsLabel(audit.economics);
    const decision = audit.decision ?? audit.next_action ?? null;
    const nextAction = audit.next_action ?? audit.decision ?? null;
    const hardGates = Array.isArray(audit.hard_gates) ? [...audit.hard_gates] : [];
    const promotion = derivePromotionState(
      audit.risk_state ?? audit.lifecycle_state ?? decision ?? row.commercialDecision,
    );
    const competitionCount = optionalNumber(
      audit.observed_values as Record<string, unknown> | undefined,
      "marketplace_evidence_count",
    );
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
    const freshnessClass: EvidenceClass = stale
      ? "stale"
      : classifyEvidenceClass({ evidenceMode: row.evidenceMode, pillarId: "freshness" });
    const rowRefs = Array.isArray(audit.evidence_refs) && audit.evidence_refs.length
      ? [...audit.evidence_refs]
      : refs;
    return {
      ...row,
      productTitle: audit.title ?? row.productTitle ?? row.title,
      sku,
      marketLane: mapLane(audit, options.packetLane) ?? row.marketLane,
      supplierOffer: summarizeOffer(audit),
      assumptions: Array.isArray(audit.assumptions) ? [...audit.assumptions] : row.assumptions,
      missingEvidence: Array.isArray(audit.missing_evidence) ? [...audit.missing_evidence] : row.missingEvidence,
      conflicts: Array.isArray(audit.conflicts) ? [...audit.conflicts] : row.conflicts,
      confidence: overall,
      confidenceSupplier: supplierConf,
      confidenceMarketplace: marketConf,
      commercialDecision: decision ?? row.commercialDecision,
      nextBestAction: nextAction ?? row.nextBestAction,
      promotionState: promotion,
      riskLevel: audit.risk_state ?? row.riskLevel,
      hardGates,
      evidenceReferences: rowRefs.length ? rowRefs : row.evidenceReferences,
      consumerAttentionSummary: consumerStatus,
      competitionSummary: competitionCount !== null
        ? `marketplace_evidence_count_${competitionCount}`
        : row.competitionSummary,
      replayIdentity: options.replayIdentity ?? row.replayIdentity,
      freshnessExpiry: expiry,
      supplierEvidenceClass: supplierClass,
      consumerEvidenceClass: consumerClass,
      economicsUnavailable: economicsMissing,
      economicsLabel: economicsMissing ? null : (mappedEconomics ?? row.economicsLabel),
      pillarCells: row.pillarCells.map((cell): typeof cell => {
        if (cell.pillarId === "consumer_attention") {
          return {
            ...cell,
            evidenceClass: consumerClass,
            status: consumerClass === "not_run" ? "unavailable" : cell.status,
          };
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
            detail: audit.freshness ?? freshnessLabel ?? cell.detail,
          };
        }
        return cell;
      }),
    };
  });

  const unmatchedProjectionIds = [...projectionIds].filter((id) => !matched.has(id));
  return { rows: nextRows, unmatchedServerIds, unmatchedProjectionIds, warning: null };
}

/** Single compatibility adapter for product-validation-report-v1 + appendix v1. */
export function adaptResearchToDecisionProjection(
  rows: RankedCandidateRow[],
  raw: unknown,
  nowMs: number = Date.now(),
): ProjectionAdapterResult {
  if (raw == null) {
    return {
      rows,
      warning: null,
      accepted: false,
      replayIdentity: null,
      unmatchedServerIds: [],
      unmatchedProjectionIds: [],
    };
  }
  const validated = validateResearchToDecisionProjection(raw);
  if (!validated.ok) {
    return {
      rows,
      warning: validated.reason,
      accepted: false,
      replayIdentity: null,
      unmatchedServerIds: [],
      unmatchedProjectionIds: [],
    };
  }
  const appendix = validated.packet.appendix;
  const reportsNetwork = appendix.validation?.network_calls === true
    || appendix.client_safe_projection?.network_calls === true;
  const authorities = appendix.source_authorities ?? {};
  const refs = Object.values(authorities).filter((value) => typeof value === "string");
  const consumerStatus = validated.packet.executive_summary?.consumer_attention_signals?.status ?? null;
  const overlaid = overlayResearchToDecisionAudits(rows, appendix.candidate_audit, {
    replayIdentity: appendix.replay_fingerprint ?? null,
    evidenceReferences: refs,
    consumerAttentionStatus: consumerStatus,
    packetLane: appendix.market_lane,
    nowMs,
    clientSafeCandidates: appendix.client_safe_projection?.candidates,
  });
  const warnings = [
    overlaid.warning,
    reportsNetwork ? "projection_reports_network_calls" : null,
  ].filter((value): value is string => Boolean(value));
  return {
    rows: overlaid.rows,
    warning: warnings.join(",") || null,
    accepted: overlaid.warning == null,
    replayIdentity: appendix.replay_fingerprint ?? null,
    unmatchedServerIds: overlaid.unmatchedServerIds,
    unmatchedProjectionIds: overlaid.unmatchedProjectionIds,
  };
}

export function overlayResearchToDecisionProjection(
  rows: RankedCandidateRow[],
  raw: unknown,
  nowMs: number = Date.now(),
): ProjectionAdapterResult {
  return adaptResearchToDecisionProjection(rows, raw, nowMs);
}
