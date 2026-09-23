/**
 * Draft marketing/publicity strategy packet.
 * Planning records only. Nothing here authorizes publish, spend, outbound, or provider calls.
 */

export const STRATEGY_SCHEMA = "marketos.marketing_strategy.draft.v1" as const;

export const OFFER_KINDS = ["service", "goods", "hybrid"] as const;
export type OfferKind = (typeof OFFER_KINDS)[number];

export const EVIDENCE_CLASSES = [
  "fixture",
  "manual",
  "simulated",
  "unknown",
  "stale",
  "assumption",
] as const;
export type EvidenceClass = (typeof EVIDENCE_CLASSES)[number];

export const PACKET_SURFACES = [
  "complete",
  "partial",
  "stale",
  "conflicting",
  "no_evidence",
  "unavailable",
] as const;
export type PacketSurface = (typeof PACKET_SURFACES)[number];

export interface EvidenceRef {
  evidence_id: string;
  evidence_class: EvidenceClass;
  label: string;
  as_of: string | null;
}

export interface StrategyClaim {
  claim_id: string;
  text: string;
  evidence_ids: string[];
}

export interface AudienceSegment {
  segment_id: string;
  label: string;
  description: string;
}

export interface MessageNode {
  message_id: string;
  level: "primary" | "support" | "proof";
  text: string;
}

export interface OfferAngle {
  angle_id: string;
  kind: OfferKind;
  headline: string;
  planning_note: string;
}

export interface PublicityAngle {
  angle_id: string;
  outlet_type: string;
  pitch: string;
}

export interface ContentPillar {
  pillar_id: string;
  name: string;
  intent: string;
}

export interface PaidTestCell {
  cell_id: string;
  channel: string;
  hypothesis: string;
  budget_assumption_label: string;
}

export interface UgcBrief {
  brief_id: string;
  prompt_for_creator: string;
  internal_only: boolean;
}

export interface CalendarItem {
  item_id: string;
  week_label: string;
  channel: string;
  draft_title: string;
}

export interface ChannelRecommendation {
  channel_id: string;
  channel: string;
  rationale: string;
  evidence_ids: string[];
}

export interface KpiDefinition {
  kpi_id: string;
  name: string;
  definition: string;
  assumption: boolean;
}

export interface BudgetScenario {
  scenario_id: string;
  name: string;
  amount_label: string;
  assumption: true;
}

export interface MeasurementStep {
  step_id: string;
  description: string;
}

export interface ApprovalBlocker {
  blocker_id: string;
  reason: string;
}

export interface NextAction {
  action_id: string;
  label: string;
  requires_human: true;
}

export interface MarketingStrategyPacket {
  schema_version: typeof STRATEGY_SCHEMA;
  strategy_id: string;
  title: string;
  offer_kind: OfferKind;
  surface: PacketSurface;
  draft_only: true;
  audience: AudienceSegment[];
  positioning: string;
  messages: MessageNode[];
  offer_angles: OfferAngle[];
  claims: StrategyClaim[];
  evidence: EvidenceRef[];
  publicity: PublicityAngle[];
  pillars: ContentPillar[];
  paid_tests: PaidTestCell[];
  ugc_briefs: UgcBrief[];
  calendar: CalendarItem[];
  channels: ChannelRecommendation[];
  kpis: KpiDefinition[];
  budgets: BudgetScenario[];
  measurement: MeasurementStep[];
  blockers: ApprovalBlocker[];
  next_actions: NextAction[];
}

export const FORBIDDEN_AUTHORITY = [
  "publish",
  "spend",
  "send_message",
  "place_order",
  "provider_mutate",
] as const;
