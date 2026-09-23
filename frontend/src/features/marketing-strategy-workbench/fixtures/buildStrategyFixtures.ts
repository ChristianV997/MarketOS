import type { MarketingStrategyPacket, OfferKind, PacketSurface } from "../contracts/marketingStrategyPacket.ts";
import { STRATEGY_SCHEMA } from "../contracts/marketingStrategyPacket.ts";

function base(kind: OfferKind, surface: PacketSurface, id: string): MarketingStrategyPacket {
  return {
    schema_version: STRATEGY_SCHEMA,
    strategy_id: id,
    title: `${kind} draft publicity plan`,
    offer_kind: kind,
    surface,
    draft_only: true,
    audience: [
      { segment_id: "seg-1", label: "Operators evaluating a first offer", description: "Planning segment, not a live list." },
    ],
    positioning: "A reviewed draft. Not a launched campaign.",
    messages: [
      { message_id: "m1", level: "primary", text: "Show the planning recommendation beside its evidence." },
      { message_id: "m2", level: "support", text: "Keep spend and publishing outside this review." },
    ],
    offer_angles: [
      { angle_id: "a1", kind, headline: `${kind} angle`, planning_note: "Draft angle only." },
    ],
    claims: [
      { claim_id: "c1", text: "Audience interest is described from the attached evidence.", evidence_ids: ["ev-1"] },
      { claim_id: "c2", text: "A second claim has no evidence yet.", evidence_ids: [] },
    ],
    evidence: [
      {
        evidence_id: "ev-1",
        evidence_class: surface === "stale" ? "stale" : "fixture",
        label: "Planning note",
        as_of: surface === "stale" ? "2024-01-01" : "2026-09-01",
      },
      { evidence_id: "ev-2", evidence_class: "manual", label: "Manual import", as_of: "2026-08-01" },
      { evidence_id: "ev-3", evidence_class: "assumption", label: "Budget assumption", as_of: null },
    ],
    publicity: [{ angle_id: "p1", outlet_type: "trade note", pitch: "Draft pitch. Do not send." }],
    pillars: [{ pillar_id: "pillar-1", name: "Proof stories", intent: "Organic pillar for review." }],
    paid_tests: [
      {
        cell_id: "cell-1",
        channel: "search",
        hypothesis: "Planning cell only.",
        budget_assumption_label: "Assumption, not a spend order",
      },
    ],
    ugc_briefs: [
      { brief_id: "ugc-1", prompt_for_creator: "Show the product in use. Draft brief.", internal_only: false },
      { brief_id: "ugc-internal", prompt_for_creator: "internal prompt hidden", internal_only: true },
    ],
    calendar: [{ item_id: "cal-1", week_label: "Week 1", channel: "owned site", draft_title: "Draft post" }],
    channels: [{ channel_id: "ch-1", channel: "owned site", rationale: "Review first.", evidence_ids: ["ev-1"] }],
    kpis: [{ kpi_id: "kpi-1", name: "Qualified reviews", definition: "Count of human reviews of this draft.", assumption: true }],
    budgets: [{ scenario_id: "b1", name: "Low", amount_label: "planning assumption 0", assumption: true }],
    measurement: [{ step_id: "ms-1", description: "Compare draft claims to attached evidence labels." }],
    blockers: [{ blocker_id: "blk-1", reason: "Human approval required before any external action." }],
    next_actions: [{ action_id: "n1", label: "Review claims that lack evidence.", requires_human: true }],
  };
}

export function buildComplete(kind: OfferKind = "service"): MarketingStrategyPacket {
  return base(kind, "complete", `strategy-${kind}-complete`);
}

export function buildPartial(): MarketingStrategyPacket {
  const packet = base("goods", "partial", "strategy-goods-partial");
  packet.publicity = [];
  packet.calendar = [];
  return packet;
}

export function buildStale(): MarketingStrategyPacket {
  return base("hybrid", "stale", "strategy-hybrid-stale");
}

export function buildConflicting(): MarketingStrategyPacket {
  const packet = base("hybrid", "conflicting", "strategy-hybrid-conflict");
  packet.claims[0].evidence_ids = ["ev-1", "ev-2"];
  return packet;
}

export function buildNoEvidence(): MarketingStrategyPacket {
  const packet = base("service", "no_evidence", "strategy-service-none");
  packet.claims = [{ claim_id: "c-none", text: "Unsourced claim.", evidence_ids: [] }];
  packet.evidence = [];
  return packet;
}
