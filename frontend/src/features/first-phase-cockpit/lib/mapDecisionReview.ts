import {
  COMMERCIAL_REVIEW_TAGS,
  DECISION_TIMELINE_KINDS,
  LIVE_PROOF_EVIDENCE_CLASSES,
  type CommercialReviewTag,
  type DecisionTimelineEvent,
  type NextActionWorkflow,
  type PromotionTransition,
  type RankedCandidateRow,
} from "../contracts/firstPhaseEvidencePacket.ts";

const MUTATION_ACTION = /send_message|place_order|publish_ad|change_price|approve_supplier|issue_refund|mutate/;

function timelineEvent(
  kind: DecisionTimelineEvent["kind"],
  observed: boolean,
  summary: string,
): DecisionTimelineEvent {
  return {
    kind,
    status: observed ? "observed" : "unavailable",
    summary: observed ? summary : "unavailable",
    at: null,
  };
}

export function mapDecisionTimeline(row: RankedCandidateRow): DecisionTimelineEvent[] {
  const offerObserved = Boolean(row.supplierOffer) || row.offerDisposition !== "unavailable";
  const economicsObserved = !row.economicsUnavailable && Boolean(row.economicsLabel);
  const competitionObserved = Boolean(row.competitionSummary);
  const promotionObserved = row.promotionState !== "unavailable";
  const decisionObserved = Boolean(row.commercialDecision);
  const blockerObserved = row.hardGates.length > 0 || Boolean(row.nextBestAction) || row.missingEvidence.length > 0;
  const replayObserved = Boolean(row.replayIdentity);
  const freshnessObserved = Boolean(row.freshnessExpiry);
  const evidenceObserved = row.evidenceClass !== "unavailable" && row.evidenceClass !== "not_run";

  return [
    timelineEvent("evidence_captured", evidenceObserved, `${row.evidenceMode} · ${row.evidenceClass}`),
    timelineEvent("supplier_offer_normalized", Boolean(row.sku || row.supplierOffer), row.sku ?? row.supplierOffer ?? "unavailable"),
    timelineEvent(
      "offer_accepted_or_quarantined",
      offerObserved && row.offerDisposition !== "unavailable",
      row.offerDisposition,
    ),
    timelineEvent("economics_calculated", economicsObserved, row.economicsLabel ?? "unavailable"),
    timelineEvent("competition_market_status", competitionObserved, row.competitionSummary ?? "unavailable"),
    timelineEvent("promotion_gate_evaluated", promotionObserved, row.promotionState),
    timelineEvent("lifecycle_decision", decisionObserved, row.commercialDecision ?? "unavailable"),
    timelineEvent(
      "blocker_or_next_best_action",
      blockerObserved,
      row.hardGates[0] ?? row.nextBestAction ?? row.missingEvidence[0] ?? "unavailable",
    ),
    timelineEvent("replay_identity", replayObserved, row.replayIdentity ?? "unavailable"),
    timelineEvent("evidence_freshness_expiry", freshnessObserved, row.freshnessExpiry ?? "unavailable"),
  ];
}

export function mapCommercialReviewTags(row: RankedCandidateRow): CommercialReviewTag[] {
  const tags = new Set<CommercialReviewTag>();
  tags.add("launch_authorized_false");
  if (row.promotionState === "screening") tags.add("screening");
  if (row.promotionState === "needs_evidence" || row.missingEvidence.length > 0) tags.add("needs_evidence");
  if (row.promotionState === "hold") tags.add("hold");
  if (row.promotionState === "reject") tags.add("reject");
  if (row.promotionState === "blocked") tags.add("blocked");
  if (row.promotionState === "draft_ready") tags.add("draft_ready");
  if (row.promotionState === "unavailable") tags.add("unavailable");
  if (
    row.evidenceClass === "stale"
    || (row.freshnessExpiry ?? "").toLowerCase().includes("expir")
    || row.pillarCells.some((cell) => cell.pillarId === "freshness" && cell.evidenceClass === "stale")
  ) {
    tags.add("stale");
  }
  if (row.evidenceMode === "fixture_only") tags.add("fixture");
  if (row.evidenceMode === "manual") tags.add("manual_import");
  if (row.evidenceMode === "simulated") tags.add("simulated");
  if (row.evidenceMode === "live_readonly") tags.add("live_readonly");
  if (
    row.evidenceMode === "live_readonly"
    && LIVE_PROOF_EVIDENCE_CLASSES.has(row.evidenceClass)
  ) {
    tags.add("live_validated");
  }
  return COMMERCIAL_REVIEW_TAGS.filter((tag) => tags.has(tag));
}

export function mapNextActionWorkflow(row: RankedCandidateRow): NextActionWorkflow {
  const action = row.nextBestAction ?? "unavailable";
  const mutation = MUTATION_ACTION.test(action);
  let responsibleParty: NextActionWorkflow["responsibleParty"] = "unavailable";
  if (action !== "unavailable") {
    if (action.includes("client") || action.includes("ask_")) responsibleParty = "client";
    else if (action.includes("supplier")) responsibleParty = "supplier";
    else responsibleParty = "operator";
  }
  return {
    action,
    missingEvidence: [...row.missingEvidence],
    responsibleParty,
    expectedEvidenceType: row.missingEvidence[0] ?? row.validationTarget ?? "unavailable",
    humanConfirmationRequired:
      row.promotionState === "hold"
      || row.promotionState === "needs_evidence"
      || action.includes("review")
      || action.includes("confirm"),
    allowedInReadOnlyCockpit: false,
    futureActionStatus: mutation || action === "unavailable" ? "unavailable" : "draft",
    futureActionNote:
      "Cockpit cannot send messages, place orders, publish ads, change prices, approve suppliers, issue refunds, or mutate external systems.",
  };
}

export function mapPromotionTransitions(row: RankedCandidateRow): PromotionTransition[] {
  if (row.promotionTransitions?.some((item) => item.status === "observed")) {
    return row.promotionTransitions;
  }
  return [{
    from: null,
    to: row.promotionState,
    status: row.promotionState === "unavailable" ? "unavailable" : "observed",
    reason: row.commercialDecision,
  }];
}

export function enrichDecisionReview(row: RankedCandidateRow): RankedCandidateRow {
  const withDisposition: RankedCandidateRow = {
    ...row,
    offerDisposition: row.offerDisposition ?? "unavailable",
    launchAuthorizedFalse: true,
    promotionTransitions: row.promotionTransitions ?? [],
    decisionTimeline: [],
    commercialReviewTags: [],
    nextActionWorkflow: row.nextActionWorkflow ?? mapNextActionWorkflow(row),
  };
  return {
    ...withDisposition,
    decisionTimeline: mapDecisionTimeline(withDisposition),
    commercialReviewTags: mapCommercialReviewTags(withDisposition),
    nextActionWorkflow: mapNextActionWorkflow(withDisposition),
    promotionTransitions: mapPromotionTransitions(withDisposition),
    launchAuthorizedFalse: true,
  };
}

export { DECISION_TIMELINE_KINDS };
