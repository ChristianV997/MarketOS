/**
 * Owner research workspace: opportunity review + curated portfolio.
 *
 * Read-only view-model contracts. This surface is separate from the
 * client-services CRM and carries no publishing, spend, order, provider or
 * mutation authority.
 *
 * Two inputs, deliberately kept apart:
 *
 * 1. RANKING read model - the canonical `FirstPhaseEvidencePacket`
 *    (`phase1-evidence-cockpit-v1` view model). Its server route
 *    `GET /api/phase1/evidence-cockpit` is documented as NOT implemented, so the
 *    packet is composed client-side from existing canonical read endpoints.
 *    Product Opportunity Synthesis stays the ranking authority: this UI
 *    preserves backend order and never computes, blends or backfills a score.
 *
 * 2. PORTFOLIO read model - `owner-research-portfolio-v1`. NO backend route
 *    serves this contract on main. It is a typed adapter boundary: until a
 *    backend implements it the surface reports `unavailable`, never `0/3`.
 */

import type {
  EvidenceClass,
  EvidenceMode,
  PillarId,
} from "../../first-phase-cockpit/contracts/firstPhaseEvidencePacket";

export type { EvidenceClass, EvidenceMode, PillarId };
export { MAX_PROJECTION_CANDIDATES as MAX_RANKED_ROWS } from "../../first-phase-cockpit/contracts/firstPhaseEvidencePacket";

// ---------------------------------------------------------------------------
// Portfolio read-model contract (PROPOSED - not served by any route on main)
// ---------------------------------------------------------------------------

export const OWNER_PORTFOLIO_SCHEMA_VERSION = "owner-research-portfolio-v1" as const;

/**
 * Proposed read-only path. It does not exist on main; a 404/405/501 is surfaced
 * as `unavailable` (endpoint_not_available), not as an empty portfolio.
 */
export const OWNER_PORTFOLIO_ENDPOINT = "/api/owner-research/portfolio" as const;

/** Product rule: draft research needs at least this many distinct active candidates. */
export const PORTFOLIO_REQUIRED_ACTIVE_CANDIDATES = 3;
export const MAX_PORTFOLIO_ITEMS = 500;
export const MAX_CANDIDATE_ID_LENGTH = 128;

export const PORTFOLIO_ITEM_STATUSES = ["active", "inactive", "removed", "archived"] as const;
export type PortfolioItemStatus = (typeof PORTFOLIO_ITEM_STATUSES)[number];

/**
 * One portfolio entry. Only `candidate_id` and `status` are read for progress.
 * `sku`, supplier offers and quantities may be present (a backend can emit one
 * row per SKU/offer) and are deliberately ignored: identity is the candidate id.
 */
export interface OwnerPortfolioItemV1 {
  candidate_id: string;
  status: PortfolioItemStatus;
  title?: string | null;
  sku?: string | null;
  supplier_offer_count?: number | null;
  quantity?: number | null;
  added_at?: string | null;
}

export interface OwnerPortfolioReadModelV1 {
  schema_version: typeof OWNER_PORTFOLIO_SCHEMA_VERSION;
  workspace_id: string;
  generated_at?: string | null;
  /** Explicit expiry; when absent freshness falls back to generated_at age. */
  expires_at?: string | null;
  evidence_mode: EvidenceMode;
  items: OwnerPortfolioItemV1[];
  /**
   * Backend-owned eligibility for draft research. Only a strict boolean `true`
   * can ever enable actions; a missing block means "not reported".
   */
  draft_research?: { eligible: boolean; reasons?: string[] };
  read_only: true;
  mutated: false;
  network_calls?: boolean;
}

// ---------------------------------------------------------------------------
// Draft-research actions (advisory drafts only; wired by the integrator)
// ---------------------------------------------------------------------------

export const DRAFT_RESEARCH_ACTIONS = [
  { id: "target_markets", label: "Target markets" },
  { id: "personas", label: "Customer personas" },
  { id: "brand_ad_strategy", label: "Brand, marketing and ad strategy" },
  { id: "social_channels", label: "Social channel and account suggestions" },
  { id: "storefront_landing", label: "Ecommerce and landing-page options" },
] as const;

export type DraftResearchActionId = (typeof DRAFT_RESEARCH_ACTIONS)[number]["id"];

/** Intent emitted to the integrator. This feature performs no network call itself. */
export interface DraftResearchRequest {
  actionId: DraftResearchActionId;
  activeCandidateIds: readonly string[];
}

// ---------------------------------------------------------------------------
// Surface state
// ---------------------------------------------------------------------------

export type SurfaceScope = "ranking" | "portfolio";

/**
 * Exclusive phase. `unavailable` (no read model / no contract / no workspace)
 * is distinct from `error` (a request or payload failed) and from `empty`
 * (a valid response with zero entries).
 */
export type SurfacePhase = "loading" | "error" | "unavailable" | "empty" | "ready";

/** Qualifiers may co-occur with a phase and each has its own banner. */
export type SurfaceQualifier = "fixture" | "stale" | "partial" | "blocked";

// ---------------------------------------------------------------------------
// Ranking view model
// ---------------------------------------------------------------------------

export type FreshnessStatus = "fresh" | "stale" | "not_reported" | "invalid";

export interface FreshnessView {
  status: FreshnessStatus;
  /** Human sentence; never invents a timestamp. */
  label: string;
  expiresAt: string | null;
}

export type PillarStatus = "available" | "partial" | "unavailable" | "blocked";

export interface PillarReview {
  id: PillarId;
  label: string;
  status: PillarStatus;
  /** As reported by the backend; null means "not reported", never zero. */
  score: number | null;
  detail: string | null;
  evidenceClass: EvidenceClass;
}

export interface OpportunityProvenance {
  sourceFamily: string | null;
  evidenceMode: EvidenceMode;
  evidenceClass: EvidenceClass;
  supplierEvidenceClass: EvidenceClass;
  consumerEvidenceClass: EvidenceClass;
  evidenceReferences: string[];
  replayIdentity: string | null;
}

export interface OpportunityRow {
  candidateId: string;
  title: string | null;
  /** 1-based rank from the backend `rankIndex`; null when the backend value is unusable. */
  rankNumber: number | null;
  /** 1-based position in the backend-ordered array. */
  position: number;
  evidenceCompleteness: number | null;
  confidence: number | null;
  riskLevel: string | null;
  commercialDecision: string | null;
  promotionState: string;
  nextBestAction: string | null;
  pillars: PillarReview[];
  /** Evidence still missing, exactly as reported. */
  gaps: string[];
  hardGates: string[];
  conflicts: string[];
  assumptions: string[];
  provenance: OpportunityProvenance;
  freshness: FreshnessView;
  /** True when any pillar is not `available` or evidence gaps are reported. */
  partial: boolean;
  /** Set by the workspace once the portfolio has loaded; never guessed. */
  inPortfolio: boolean | null;
}

export interface RankingRunMeta {
  schemaVersion: string | null;
  reportVersion: string | null;
  generatedAt: string | null;
  freshness: FreshnessView;
  sourceLabels: string[];
  sourceFamilies: string[];
  overallStatus: string | null;
  nextBestAction: string | null;
  readOnly: boolean;
  networkCalls: boolean;
}

export interface DroppedRow {
  reason: "invalid_candidate_id" | "duplicate_candidate_id" | "rows_truncated";
  candidateId: string | null;
}

export interface OpportunityReviewModel {
  phase: SurfacePhase;
  qualifiers: SurfaceQualifier[];
  reasons: string[];
  warnings: string[];
  evidenceMode: EvidenceMode | null;
  run: RankingRunMeta | null;
  rows: OpportunityRow[];
  dropped: DroppedRow[];
}

// ---------------------------------------------------------------------------
// Portfolio view model
// ---------------------------------------------------------------------------

export interface PortfolioIgnoredCounts {
  invalidId: number;
  unknownStatus: number;
  malformedEntries: number;
  notActive: number;
  duplicateActiveRows: number;
}

export interface PortfolioEligibility {
  /** True only when the backend supplied a strict boolean. */
  reported: boolean;
  eligible: boolean;
  reasons: string[];
  /** Backend says eligible but the distinct active count is below the requirement. */
  conflict: boolean;
}

export interface PortfolioReviewModel {
  phase: SurfacePhase;
  qualifiers: SurfaceQualifier[];
  reasons: string[];
  workspaceId: string | null;
  evidenceMode: EvidenceMode | null;
  /** Distinct, active, well-formed candidate ids in first-seen order. */
  activeCandidateIds: string[];
  /** null while loading/unavailable/error: unknown is never rendered as zero. */
  activeCount: number | null;
  required: number;
  ignored: PortfolioIgnoredCounts;
  eligibility: PortfolioEligibility;
  freshness: FreshnessView;
  generatedAt: string | null;
}

export interface DraftResearchGate {
  enabled: boolean;
  /** Every reason the actions are disabled; empty only when enabled. */
  reasons: string[];
}
