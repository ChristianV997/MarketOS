import type {
  CandidatePillarCell,
  FirstPhaseEvidencePacket,
  RankedCandidateRow,
} from "../../first-phase-cockpit/contracts/firstPhaseEvidencePacket";
import { isStaleFreshness } from "../../first-phase-cockpit/lib/freshness";
import {
  MAX_RANKED_ROWS,
  type DroppedRow,
  type OpportunityReviewModel,
  type OpportunityRow,
  type PillarReview,
  type SurfaceQualifier,
} from "../contracts/ownerResearch";
import { isStableCandidateId } from "./candidateId";
import { describeFreshness, FRESHNESS_NOT_REPORTED } from "./freshnessView";
import { finiteOrNull, stringList, uniqueStrings } from "./format";

export interface RankingAdapterInput {
  /** The canonical packet, or null when no read model has been provided. */
  packet: FirstPhaseEvidencePacket | null;
  loading: boolean;
  /** Set by the container when a canonical read failed hard (not merely absent). */
  loadError: string | null;
  nowMs: number;
}

const EMPTY: OpportunityReviewModel = Object.freeze({
  phase: "unavailable",
  qualifiers: [],
  reasons: [],
  warnings: [],
  evidenceMode: null,
  run: null,
  rows: [],
  dropped: [],
}) as OpportunityReviewModel;

function blank(
  phase: OpportunityReviewModel["phase"],
  reasons: string[],
): OpportunityReviewModel {
  return { ...EMPTY, phase, reasons, qualifiers: [], warnings: [], rows: [], dropped: [] };
}

function mapPillar(cell: CandidatePillarCell): PillarReview {
  return {
    id: cell.pillarId,
    label: cell.label,
    status: cell.status,
    score: finiteOrNull(cell.score),
    detail: cell.detail ?? null,
    evidenceClass: cell.evidenceClass,
  };
}

function toRow(candidate: RankedCandidateRow, index: number, nowMs: number): OpportunityRow {
  const pillars = Array.isArray(candidate.pillarCells) ? candidate.pillarCells.map(mapPillar) : [];
  const gaps = stringList(candidate.missingEvidence);
  const rankIndex = finiteOrNull(candidate.rankIndex);
  return {
    candidateId: candidate.candidateId,
    title: (candidate.title || candidate.productTitle || "").trim() || null,
    rankNumber: rankIndex !== null && Number.isInteger(rankIndex) && rankIndex >= 0 ? rankIndex + 1 : null,
    position: index + 1,
    evidenceCompleteness: finiteOrNull(candidate.evidenceCompleteness),
    confidence: finiteOrNull(candidate.confidence),
    riskLevel: candidate.riskLevel ?? null,
    commercialDecision: candidate.commercialDecision ?? null,
    promotionState: candidate.promotionState,
    nextBestAction: candidate.nextBestAction ?? null,
    pillars,
    gaps,
    hardGates: stringList(candidate.hardGates),
    conflicts: stringList(candidate.conflicts),
    assumptions: stringList(candidate.assumptions),
    provenance: {
      sourceFamily: candidate.sourceFamily ?? null,
      evidenceMode: candidate.evidenceMode,
      evidenceClass: candidate.evidenceClass,
      supplierEvidenceClass: candidate.supplierEvidenceClass,
      consumerEvidenceClass: candidate.consumerEvidenceClass,
      evidenceReferences: stringList(candidate.evidenceReferences),
      replayIdentity: candidate.replayIdentity ?? null,
    },
    freshness: describeFreshness({ expiresAt: candidate.freshnessExpiry, nowMs }),
    partial: gaps.length > 0 || pillars.some((pillar) => pillar.status !== "available"),
    inPortfolio: null,
  };
}

function mapRows(
  candidates: readonly RankedCandidateRow[],
  nowMs: number,
): { rows: OpportunityRow[]; dropped: DroppedRow[]; warnings: string[] } {
  const rows: OpportunityRow[] = [];
  const dropped: DroppedRow[] = [];
  const warnings: string[] = [];
  const seen = new Set<string>();

  for (let index = 0; index < candidates.length; index += 1) {
    if (rows.length >= MAX_RANKED_ROWS) {
      dropped.push({ reason: "rows_truncated", candidateId: null, count: candidates.length - index });
      break;
    }
    const candidate = candidates[index];
    if (!isStableCandidateId(candidate?.candidateId)) {
      dropped.push({ reason: "invalid_candidate_id", candidateId: null, count: 1 });
      continue;
    }
    if (seen.has(candidate.candidateId)) {
      dropped.push({ reason: "duplicate_candidate_id", candidateId: candidate.candidateId, count: 1 });
      continue;
    }
    seen.add(candidate.candidateId);
    rows.push(toRow(candidate, index, nowMs));
  }

  // The backend order is the ranking. Surface (never repair) an inconsistent rankIndex.
  let previous = -1;
  for (const row of rows) {
    if (row.rankNumber === null) {
      warnings.push(`rank_index_invalid:${row.candidateId}`);
      continue;
    }
    if (row.rankNumber <= previous) warnings.push(`rank_order_inconsistent:${row.candidateId}`);
    previous = Math.max(previous, row.rankNumber);
  }
  for (const item of dropped) {
    if (item.candidateId) warnings.push(`${item.reason}:${item.candidateId}`);
    else warnings.push(item.reason === "rows_truncated" ? `${item.reason}:${item.count}` : item.reason);
  }
  return { rows, dropped, warnings };
}

/**
 * Canonical ranking packet -> review model. Order is the backend order; nothing
 * is re-scored, re-sorted or backfilled, and missing values stay null.
 */
export function adaptRankingPacket(input: RankingAdapterInput): OpportunityReviewModel {
  if (input.loading) return blank("loading", []);

  const { packet } = input;
  if (!packet) {
    return input.loadError
      ? blank("error", [input.loadError])
      : blank("unavailable", ["ranking_read_model_not_provided"]);
  }
  if (packet.state === "loading") return blank("loading", []);

  if (packet.fingerprint.readOnly !== true) {
    return blank("error", ["ranking_read_model_not_read_only"]);
  }

  const reasons = uniqueStrings([...packet.blockedReasons, ...packet.unavailableReasons]);
  const evidenceMode = packet.fingerprint.evidenceMode;
  const freshness = packet.fingerprint.generatedAt
    ? describeFreshness({ generatedAt: packet.fingerprint.generatedAt, nowMs: input.nowMs })
    : FRESHNESS_NOT_REPORTED;

  const run = {
    schemaVersion: packet.fingerprint.schemaVersion,
    reportVersion: packet.fingerprint.reportVersion,
    generatedAt: packet.fingerprint.generatedAt,
    freshness,
    sourceLabels: [...packet.fingerprint.sourceLabels],
    sourceFamilies: [...packet.fingerprint.sourceFamilies],
    overallStatus: packet.fingerprint.overallStatus,
    nextBestAction: packet.fingerprint.nextBestAction,
    readOnly: packet.fingerprint.readOnly,
    networkCalls: packet.fingerprint.networkCalls,
  };

  const qualifiers: SurfaceQualifier[] = [];
  if (evidenceMode === "fixture_only" || evidenceMode === "simulated") qualifiers.push("fixture");

  // Rows from an unavailable/errored read model are not trusted and are never shown.
  const mapped = mapRows(packet.rankedCandidates ?? [], input.nowMs);

  if (input.loadError && mapped.rows.length === 0) {
    return { ...blank("error", [input.loadError]), qualifiers, evidenceMode, run };
  }
  if (packet.state === "unavailable") {
    return {
      ...blank("unavailable", reasons.length ? reasons : ["ranking_read_model_unavailable"]),
      qualifiers,
      evidenceMode,
      run,
    };
  }

  // Own computation wins when a generation time is reported; the packet's static label is only a fallback.
  const labelStale = !packet.fingerprint.generatedAt && isStaleFreshness(packet.fingerprint.freshnessLabel);
  const stale = packet.state === "stale" || freshness.status === "stale" || labelStale;
  if (stale) qualifiers.push("stale");
  const partial =
    packet.state === "partial"
    || mapped.dropped.length > 0
    || Boolean(input.loadError)
    || mapped.warnings.some((warning) => warning.startsWith("rank_"));
  if (partial) qualifiers.push("partial");
  if (packet.state === "blocked") qualifiers.push("blocked");

  const allReasons = input.loadError ? uniqueStrings([input.loadError, ...reasons]) : reasons;

  return {
    phase: mapped.rows.length === 0 ? "empty" : "ready",
    qualifiers,
    reasons: allReasons,
    warnings: uniqueStrings([...packet.warnings, ...mapped.warnings]),
    evidenceMode,
    run,
    rows: mapped.rows,
    dropped: mapped.dropped,
  };
}

/** Join the loaded portfolio onto ranked rows. Unknown portfolio leaves `inPortfolio` null. */
export function markPortfolioMembership(
  rows: readonly OpportunityRow[],
  activeCandidateIds: readonly string[] | null,
): OpportunityRow[] {
  const active = activeCandidateIds ? new Set(activeCandidateIds) : null;
  return rows.map((row) => ({ ...row, inPortfolio: active ? active.has(row.candidateId) : null }));
}
