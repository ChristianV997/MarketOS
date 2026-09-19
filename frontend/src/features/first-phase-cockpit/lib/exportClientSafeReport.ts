import {
  CLIENT_SAFE_EXPORT_VERSION,
  EVIDENCE_COCKPIT_SCHEMA_VERSION,
  type ClientSafeCockpitExport,
  type FirstPhaseEvidencePacket,
} from "../contracts/firstPhaseEvidencePacket.ts";

const SECRET_SHAPED = /sk-live-|sk-test-|ghp_|github_pat_|AKIA[0-9A-Z]{16}|bearer\s+[a-z0-9._-]{10,}/i;
const FORBIDDEN_EXPORT_KEY = /prompt|formula|heuristic|source_code|private_key|provider_payload|internal_notes/;
const PATH_SHAPED = /(^|[\\/])(users|home|documents|marketos)[\\/]/i;

/** Reject strings that look like secrets before export or display. */
export function containsSecretShapedValue(value: unknown): boolean {
  if (typeof value === "string") {
    return SECRET_SHAPED.test(value) || PATH_SHAPED.test(value);
  }
  if (Array.isArray(value)) return value.some(containsSecretShapedValue);
  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>).some(([key, item]) => {
      const keyL = key.toLowerCase().replace(/-/g, "_");
      if (
        keyL.includes("password")
        || keyL.includes("secret")
        || keyL.includes("api_key")
        || keyL.includes("authorization")
        || keyL.includes("private_key")
        || keyL.includes("access_token")
        || FORBIDDEN_EXPORT_KEY.test(keyL)
      ) {
        return true;
      }
      return containsSecretShapedValue(item);
    });
  }
  return false;
}

/**
 * Build a client-safe export from the already-sanitized view model.
 * Never includes raw provider payloads, credentials, or internal formulas.
 */
export function buildClientSafeExport(
  packet: FirstPhaseEvidencePacket,
  exportedAt: string,
): ClientSafeCockpitExport {
  const schemaVersion =
    packet.fingerprint.schemaVersion === EVIDENCE_COCKPIT_SCHEMA_VERSION
      ? EVIDENCE_COCKPIT_SCHEMA_VERSION
      : "composed-live";

  const payload: ClientSafeCockpitExport = {
    export_version: CLIENT_SAFE_EXPORT_VERSION,
    schema_version: schemaVersion,
    exported_at: exportedAt,
    read_only: true,
    mutated: false,
    network_calls: false,
    state: packet.state,
    evidence_mode: packet.fingerprint.evidenceMode,
    overall_status: packet.fingerprint.overallStatus,
    next_best_action: packet.fingerprint.nextBestAction,
    source_labels: [...packet.fingerprint.sourceLabels],
    source_families: [...packet.fingerprint.sourceFamilies],
    ranked_candidates: packet.rankedCandidates.map((candidate) => ({
      candidate_id: candidate.candidateId,
      title: candidate.title,
      rank_index: candidate.rankIndex,
      evidence_completeness: candidate.evidenceCompleteness,
      supplier_score: candidate.supplierScore,
      competition_score: candidate.competitionScore,
      economics_label: candidate.economicsLabel,
      commercial_decision: candidate.commercialDecision,
      next_best_action: candidate.nextBestAction,
      risk_level: candidate.riskLevel,
      is_top_candidate: candidate.isTopCandidate,
      evidence_class: candidate.evidenceClass,
      sku: candidate.sku,
      promotion_state: candidate.promotionState,
      market_lane: candidate.marketLane,
      confidence: candidate.confidence,
      confidence_supplier: candidate.confidenceSupplier,
      confidence_marketplace: candidate.confidenceMarketplace,
      assumptions: [...candidate.assumptions],
      missing_evidence: [...candidate.missingEvidence],
      conflicts: [...candidate.conflicts],
      hard_gates: [...candidate.hardGates],
      evidence_references: [...candidate.evidenceReferences],
      consumer_attention: candidate.consumerAttentionSummary,
      competition_summary: candidate.competitionSummary,
      replay_identity: candidate.replayIdentity,
      supplier_evidence_class: candidate.supplierEvidenceClass,
      consumer_evidence_class: candidate.consumerEvidenceClass,
      economics_unavailable: candidate.economicsUnavailable,
      commercial_review_tags: [...(candidate.commercialReviewTags ?? [])],
      next_action_workflow: candidate.nextActionWorkflow,
      decision_timeline: [...(candidate.decisionTimeline ?? [])],
      launch_authorized_false: candidate.launchAuthorizedFalse ?? true,
    })),
    pillars: packet.pillars.map((pillar) => ({
      pillar_id: pillar.id,
      status: pillar.status,
      summary: pillar.summary,
      blocked_reasons: [...pillar.blockedReasons],
    })),
    control_planes: packet.controlPlanes.map((slot) => ({
      id: slot.id,
      status: slot.status,
      outcome: slot.outcome,
      blocked_reasons: [...slot.blockedReasons],
    })),
    warnings: [...packet.warnings],
    blocked_reasons: [...packet.blockedReasons],
    unavailable_reasons: [...packet.unavailableReasons],
  };

  if (containsSecretShapedValue(payload)) {
    throw new Error("client_safe_export_rejected_secret_shaped_value");
  }
  return payload;
}

export function serializeClientSafeExport(packet: FirstPhaseEvidencePacket, exportedAt: string): string {
  return `${JSON.stringify(buildClientSafeExport(packet, exportedAt), null, 2)}\n`;
}
