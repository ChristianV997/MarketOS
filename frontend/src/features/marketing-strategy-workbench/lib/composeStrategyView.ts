import type {
  EvidenceClass,
  MarketingStrategyPacket,
  StrategyClaim,
} from "../contracts/marketingStrategyPacket.ts";

export interface ClaimReview {
  claim_id: string;
  text: string;
  status: "linked" | "needs_review" | "stale" | "conflicting";
  evidence_labels: string[];
}

export interface StrategyView {
  strategy_id: string;
  title: string;
  offer_kind: MarketingStrategyPacket["offer_kind"];
  surface: MarketingStrategyPacket["surface"];
  draft_only: true;
  executed_campaign: false;
  audience: MarketingStrategyPacket["audience"];
  positioning: string;
  messages: MarketingStrategyPacket["messages"];
  offer_angles: MarketingStrategyPacket["offer_angles"];
  claims: ClaimReview[];
  publicity: MarketingStrategyPacket["publicity"];
  pillars: MarketingStrategyPacket["pillars"];
  paid_tests: MarketingStrategyPacket["paid_tests"];
  ugc_briefs: MarketingStrategyPacket["ugc_briefs"];
  calendar: MarketingStrategyPacket["calendar"];
  channels: MarketingStrategyPacket["channels"];
  kpis: MarketingStrategyPacket["kpis"];
  budgets: MarketingStrategyPacket["budgets"];
  measurement: MarketingStrategyPacket["measurement"];
  blockers: MarketingStrategyPacket["blockers"];
  next_actions: MarketingStrategyPacket["next_actions"];
  banner: string;
}

const VISIBLE: Record<EvidenceClass, string> = {
  fixture: "Fixture",
  manual: "Manual import",
  simulated: "Simulated",
  unknown: "Unknown",
  stale: "Stale",
  assumption: "Assumption",
};

export function evidenceLabel(kind: EvidenceClass): string {
  return VISIBLE[kind];
}

function reviewClaim(packet: MarketingStrategyPacket, claim: StrategyClaim): ClaimReview {
  const linked = packet.evidence.filter((item) => claim.evidence_ids.includes(item.evidence_id));
  const labels = linked.map((item) => evidenceLabel(item.evidence_class));
  if (linked.length === 0) {
    return { claim_id: claim.claim_id, text: claim.text, status: "needs_review", evidence_labels: [] };
  }
  if (packet.surface === "conflicting" && linked.length > 1) {
    return { claim_id: claim.claim_id, text: claim.text, status: "conflicting", evidence_labels: labels };
  }
  if (linked.some((item) => item.evidence_class === "stale") || packet.surface === "stale") {
    return { claim_id: claim.claim_id, text: claim.text, status: "stale", evidence_labels: labels };
  }
  return { claim_id: claim.claim_id, text: claim.text, status: "linked", evidence_labels: labels };
}

export function composeStrategyView(packet: MarketingStrategyPacket | null, unavailable = false): StrategyView {
  if (!packet || unavailable || packet.draft_only !== true) {
    return emptyView("Strategy packet unavailable. This is not an executed campaign.");
  }
  const banner =
    packet.surface === "complete"
      ? "Draft plan only. Recommendations are not published, funded, or sent."
      : packet.surface === "no_evidence"
        ? "Claims need review. No evidence is attached. Not an executed campaign."
        : `Draft plan (${packet.surface}). Not an executed campaign.`;
  return {
    strategy_id: packet.strategy_id,
    title: packet.title,
    offer_kind: packet.offer_kind,
    surface: packet.surface,
    draft_only: true,
    executed_campaign: false,
    audience: packet.audience,
    positioning: packet.positioning,
    messages: packet.messages,
    offer_angles: packet.offer_angles,
    claims: packet.claims.map((claim) => reviewClaim(packet, claim)),
    publicity: packet.publicity,
    pillars: packet.pillars,
    paid_tests: packet.paid_tests,
    ugc_briefs: packet.ugc_briefs.filter((brief) => brief.internal_only !== true),
    calendar: packet.calendar,
    channels: packet.channels,
    kpis: packet.kpis,
    budgets: packet.budgets,
    measurement: packet.measurement,
    blockers: packet.blockers,
    next_actions: packet.next_actions,
    banner,
  };
}

function emptyView(banner: string): StrategyView {
  return {
    strategy_id: "unavailable",
    title: "Marketing strategy unavailable",
    offer_kind: "hybrid",
    surface: "unavailable",
    draft_only: true,
    executed_campaign: false,
    audience: [],
    positioning: "",
    messages: [],
    offer_angles: [],
    claims: [],
    publicity: [],
    pillars: [],
    paid_tests: [],
    ugc_briefs: [],
    calendar: [],
    channels: [],
    kpis: [],
    budgets: [],
    measurement: [],
    blockers: [],
    next_actions: [],
    banner,
  };
}
