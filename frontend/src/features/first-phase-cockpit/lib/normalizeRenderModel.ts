import type { FirstPhaseEvidencePacket } from "../contracts/firstPhaseEvidencePacket";

/**
 * Stable, secret-free render model for snapshots and contract tests.
 * Order of ranked candidates is preserved exactly.
 */
export function normalizeRenderModel(packet: FirstPhaseEvidencePacket) {
  return {
    state: packet.state,
    evidence_mode: packet.fingerprint.evidenceMode,
    overall_status: packet.fingerprint.overallStatus,
    next_best_action: packet.fingerprint.nextBestAction,
    schema_version: packet.fingerprint.schemaVersion,
    report_version: packet.fingerprint.reportVersion,
    freshness_label: packet.fingerprint.freshnessLabel,
    source_families: [...packet.fingerprint.sourceFamilies],
    candidate_ids_in_order: packet.rankedCandidates.map((candidate) => candidate.candidateId),
    candidate_count: packet.rankedCandidates.length,
    top_candidate_id:
      packet.rankedCandidates.find((candidate) => candidate.isTopCandidate)?.candidateId ?? null,
    pillar_statuses: Object.fromEntries(packet.pillars.map((pillar) => [pillar.id, pillar.status])),
    control_plane_statuses: Object.fromEntries(
      packet.controlPlanes.map((slot) => [slot.id, slot.status]),
    ),
    blocked_reasons: [...packet.blockedReasons],
    unavailable_reasons: [...packet.unavailableReasons],
    warnings: [...packet.warnings],
    unmatched_server_ids: [...packet.fingerprint.unmatchedServerIds],
    unmatched_projection_ids: [...packet.fingerprint.unmatchedProjectionIds],
    projection_warning: packet.fingerprint.projectionWarning,
    read_only: packet.fingerprint.readOnly,
    network_calls: packet.fingerprint.networkCalls,
  };
}
