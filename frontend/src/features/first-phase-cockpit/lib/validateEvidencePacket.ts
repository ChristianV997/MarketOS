import {
  EVIDENCE_COCKPIT_SCHEMA_VERSION,
  SUPPORTED_EVIDENCE_COCKPIT_SCHEMA_VERSIONS,
  type ControlPlaneStatus,
  type EvidenceMode,
  type FirstPhaseEvidenceCockpitApiContract,
  type FirstPhaseEvidencePacket,
  type PillarId,
} from "../contracts/firstPhaseEvidencePacket";
import { containsSecretShapedValue } from "./exportClientSafeReport";
import { normalizeEvidenceMode } from "./composeCockpitViewModel";
import { formatFreshnessLabel, isStaleFreshness } from "./freshness";

const PILLAR_IDS = new Set<PillarId>([
  "market_evidence",
  "consumer_attention",
  "supplier_feasibility",
  "economics",
  "provenance",
  "freshness",
]);

const CONTROL_STATUSES = new Set<ControlPlaneStatus>([
  "unavailable",
  "fixture",
  "simulated",
  "stale",
  "live_readonly",
  "blocked",
]);

export type PacketValidationResult =
  | { ok: true; packet: FirstPhaseEvidenceCockpitApiContract }
  | { ok: false; reason: string };

/**
 * Reject malformed future evidence-cockpit API payloads fail-closed.
 * Does not invent rankings or fill missing candidates.
 * Does not claim the endpoint exists — only validates a packet if one is supplied.
 */
export function validateEvidenceCockpitApiPacket(raw: unknown): PacketValidationResult {
  if (!raw || typeof raw !== "object") {
    return { ok: false, reason: "packet_not_object" };
  }
  const packet = raw as Record<string, unknown>;
  if (packet.read_only !== true) return { ok: false, reason: "read_only_required" };
  if (packet.mutated !== false) return { ok: false, reason: "mutated_must_be_false" };

  const schemaVersion = packet.schema_version;
  if (typeof schemaVersion !== "string" || !schemaVersion) {
    return { ok: false, reason: "schema_version_required" };
  }
  if (!SUPPORTED_EVIDENCE_COCKPIT_SCHEMA_VERSIONS.has(schemaVersion)) {
    return { ok: false, reason: "schema_version_unsupported" };
  }

  if (typeof packet.report_version !== "string" || !packet.report_version) {
    return { ok: false, reason: "report_version_required" };
  }
  if (typeof packet.generated_at !== "string" || !packet.generated_at) {
    return { ok: false, reason: "generated_at_required" };
  }
  if (!Array.isArray(packet.ranked_candidates)) {
    return { ok: false, reason: "ranked_candidates_required" };
  }
  if (!Array.isArray(packet.pillars)) {
    return { ok: false, reason: "pillars_required" };
  }

  let previousRank = -1;
  for (const candidate of packet.ranked_candidates) {
    if (!candidate || typeof candidate !== "object") {
      return { ok: false, reason: "candidate_malformed" };
    }
    const row = candidate as Record<string, unknown>;
    if (typeof row.candidate_id !== "string" || typeof row.title !== "string") {
      return { ok: false, reason: "candidate_identity_required" };
    }
    if (typeof row.rank_index !== "number" || !Number.isInteger(row.rank_index) || row.rank_index < 0) {
      return { ok: false, reason: "candidate_rank_index_invalid" };
    }
    // Reject out-of-order rank_index sequences without re-sorting.
    if (row.rank_index < previousRank) {
      return { ok: false, reason: "candidate_rank_index_out_of_order" };
    }
    previousRank = row.rank_index;
  }
  for (const pillar of packet.pillars) {
    if (!pillar || typeof pillar !== "object") return { ok: false, reason: "pillar_malformed" };
    const row = pillar as Record<string, unknown>;
    if (typeof row.pillar_id !== "string" || !PILLAR_IDS.has(row.pillar_id as PillarId)) {
      return { ok: false, reason: "pillar_id_invalid" };
    }
  }
  for (const key of ["trustos", "governor", "approval_ledger"] as const) {
    const slot = packet[key];
    if (!slot || typeof slot !== "object") return { ok: false, reason: `${key}_required` };
    const status = (slot as Record<string, unknown>).status;
    if (typeof status !== "string" || !CONTROL_STATUSES.has(status as ControlPlaneStatus)) {
      return { ok: false, reason: `${key}_status_invalid` };
    }
  }
  if (!packet.fingerprint || typeof packet.fingerprint !== "object") {
    return { ok: false, reason: "fingerprint_required" };
  }
  if (containsSecretShapedValue(packet)) {
    return { ok: false, reason: "secret_shaped_value_rejected" };
  }
  return { ok: true, packet: packet as unknown as FirstPhaseEvidenceCockpitApiContract };
}

/** Map a validated future API packet into the cockpit view model without re-ranking. */
export function mapApiPacketToViewModel(
  api: FirstPhaseEvidenceCockpitApiContract,
  nowMs: number = Date.now(),
): FirstPhaseEvidencePacket {
  const evidenceMode: EvidenceMode = normalizeEvidenceMode(api.evidence_mode);
  const freshnessLabel = formatFreshnessLabel(api.generated_at, nowMs);
  const rankedCandidates = api.ranked_candidates.map((candidate) => ({
    candidateId: candidate.candidate_id,
    title: candidate.title,
    rankIndex: candidate.rank_index,
    evidenceCompleteness: candidate.evidence_completeness,
    supplierScore: candidate.supplier_score,
    competitionScore: candidate.competition_score,
    economicsLabel: candidate.economics_label,
    assumptionRatio: candidate.assumption_ratio,
    commercialDecision: candidate.commercial_decision,
    nextBestAction: candidate.next_best_action,
    riskLevel: candidate.risk_level,
    validationPriority: candidate.validation_priority,
    validationTarget: candidate.validation_target,
    sourceFamily: candidate.source_family,
    evidenceMode,
    isTopCandidate: candidate.is_top_candidate,
    pillarCells: (candidate.pillar_cells ?? []).map((cell) => ({
      pillarId: cell.pillar_id,
      label: cell.pillar_id.replace(/_/g, " "),
      score: cell.score,
      status: cell.status,
      detail: cell.detail,
    })),
  }));

  let state: FirstPhaseEvidencePacket["state"] = rankedCandidates.length ? "success" : "empty";
  if (api.overall_status === "blocked") state = "blocked";
  else if (api.overall_status === "degraded" || isStaleFreshness(freshnessLabel)) state = "stale";
  else if (api.overall_status === "partially_ready" || (api.unavailable_reasons?.length ?? 0) > 0) {
    state = "partial";
  }

  return {
    state,
    rankedCandidates,
    pillars: api.pillars.map((pillar) => ({
      id: pillar.pillar_id,
      label: pillar.pillar_id.replace(/_/g, " "),
      status: pillar.status,
      summary: pillar.summary,
      provenance: pillar.provenance,
      freshness: pillar.freshness,
      sourceFamily: pillar.source_family,
      evidenceMode: pillar.evidence_mode,
      blockedReasons: pillar.blocked_reasons,
    })),
    controlPlanes: [
      {
        id: "trustos",
        label: "TrustOS",
        status: api.trustos.status,
        outcome: api.trustos.outcome,
        nextBestAction: api.trustos.next_best_action,
        blockedReasons: api.trustos.blocked_reasons,
        notes: [],
      },
      {
        id: "governor",
        label: "Governor",
        status: api.governor.status,
        outcome: api.governor.outcome,
        nextBestAction: api.governor.next_best_action,
        blockedReasons: api.governor.blocked_reasons,
        notes: [],
      },
      {
        id: "approval_ledger",
        label: "Approval Ledger",
        status: api.approval_ledger.status,
        outcome: api.approval_ledger.outcome,
        nextBestAction: api.approval_ledger.next_best_action,
        blockedReasons: api.approval_ledger.blocked_reasons,
        notes: [],
      },
    ],
    fingerprint: {
      evidenceMode,
      overallStatus: api.overall_status,
      nextBestAction: api.ranked_candidates.find((c) => c.is_top_candidate)?.next_best_action
        ?? null,
      readOnly: true,
      networkCalls: Boolean(api.network_calls),
      sourceLabels: api.fingerprint.source_labels,
      sourceFamilies: api.fingerprint.source_families,
      reportVersion: api.fingerprint.report_version ?? api.report_version,
      schemaVersion: api.schema_version ?? EVIDENCE_COCKPIT_SCHEMA_VERSION,
      generatedAt: api.fingerprint.generated_at ?? api.generated_at,
      freshnessLabel,
    },
    blockedReasons: api.blocked_reasons,
    unavailableReasons: api.unavailable_reasons ?? [],
    warnings: api.warnings,
  };
}
