import {
  MAX_PORTFOLIO_ITEMS,
  OWNER_PORTFOLIO_SCHEMA_VERSION,
  PORTFOLIO_ITEM_STATUSES,
  PORTFOLIO_REQUIRED_ACTIVE_CANDIDATES,
  type DraftResearchGate,
  type EvidenceMode,
  type PortfolioIgnoredCounts,
  type PortfolioItemStatus,
  type PortfolioReviewModel,
  type SurfacePhase,
  type SurfaceQualifier,
} from "../contracts/ownerResearch";
import { isStableCandidateId } from "./candidateId";
import type { PortfolioFetchResult } from "./portfolioApi";
import { describeFreshness, FRESHNESS_NOT_REPORTED } from "./freshnessView";
import { stringList } from "./format";

const NO_IGNORED: PortfolioIgnoredCounts = Object.freeze({
  invalidId: 0,
  unknownStatus: 0,
  malformedEntries: 0,
  notActive: 0,
  duplicateActiveRows: 0,
});

/**
 * A portfolio model that carries no count. `activeCount` is null (unknown), so
 * the UI can never render a missing portfolio as 0/3.
 */
function unknownPortfolio(
  phase: Exclude<SurfacePhase, "ready" | "empty">,
  reasons: string[],
  workspaceId: string | null = null,
): PortfolioReviewModel {
  return {
    phase,
    qualifiers: [],
    reasons,
    workspaceId,
    evidenceMode: null,
    activeCandidateIds: [],
    activeCount: null,
    required: PORTFOLIO_REQUIRED_ACTIVE_CANDIDATES,
    ignored: { ...NO_IGNORED },
    eligibility: { reported: false, eligible: false, reasons: [], conflict: false },
    freshness: FRESHNESS_NOT_REPORTED,
    generatedAt: null,
  };
}

export const portfolioLoading = (workspaceId: string | null = null) => unknownPortfolio("loading", [], workspaceId);
export const portfolioUnavailable = (reason: string, workspaceId: string | null = null) =>
  unknownPortfolio("unavailable", [reason], workspaceId);
export const portfolioError = (reason: string, workspaceId: string | null = null) =>
  unknownPortfolio("error", [reason], workspaceId);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const SECRET_KEY = /(secret|token|password|passwd|api[_-]?key|authorization|credential|private[_-]?key|cookie)/i;
const MAX_SCAN_DEPTH = 10;
const MAX_SCAN_NODES = 20_000;

type KeyScan = "clean" | "secret" | "too_complex";

/**
 * Bounded deep scan for credential-shaped keys. It fails CLOSED: a payload too
 * deep or too large to scan completely is rejected, never waved through.
 */
export function scanForSecretKeys(root: unknown): KeyScan {
  let nodes = 0;
  const visit = (value: unknown, depth: number): KeyScan => {
    nodes += 1;
    if (depth > MAX_SCAN_DEPTH || nodes > MAX_SCAN_NODES) return "too_complex";
    if (Array.isArray(value)) {
      for (const item of value) {
        const result = visit(item, depth + 1);
        if (result !== "clean") return result;
      }
      return "clean";
    }
    if (!isRecord(value)) return "clean";
    for (const [key, item] of Object.entries(value)) {
      if (SECRET_KEY.test(key)) return "secret";
      const result = visit(item, depth + 1);
      if (result !== "clean") return result;
    }
    return "clean";
  };
  return visit(root, 0);
}

export function parseEvidenceMode(value: unknown): EvidenceMode {
  if (typeof value !== "string") return "unknown";
  const lowered = value.toLowerCase();
  // Fixture/simulated words win so an offline run can never read as live.
  if (lowered.includes("fixture")) return "fixture_only";
  if (lowered.includes("simul")) return "simulated";
  if (lowered.includes("manual")) return "manual";
  if (lowered === "live_readonly") return "live_readonly";
  return "unknown";
}

function isItemStatus(value: unknown): value is PortfolioItemStatus {
  return typeof value === "string" && (PORTFOLIO_ITEM_STATUSES as readonly string[]).includes(value);
}

export interface PortfolioAdapterContext {
  /** The workspace the request was made for. Required: no ambient tenant. */
  expectedWorkspaceId: string | null;
  nowMs: number;
}

/**
 * Validates an untrusted `owner-research-portfolio-v1` payload and derives the
 * progress model. Progress counts DISTINCT ACTIVE candidate ids only: SKUs,
 * supplier offers, quantities and repeated rows for one candidate never add to it.
 */
export function adaptPortfolioPayload(payload: unknown, ctx: PortfolioAdapterContext): PortfolioReviewModel {
  const expected = ctx.expectedWorkspaceId?.trim() ? ctx.expectedWorkspaceId : null;
  if (!expected) return portfolioUnavailable("workspace_not_selected");
  if (!isRecord(payload)) return portfolioError("portfolio_payload_not_object", expected);
  const keyScan = scanForSecretKeys(payload);
  if (keyScan === "secret") return portfolioError("secret_shaped_field_rejected", expected);
  if (keyScan === "too_complex") return portfolioError("payload_too_complex", expected);
  if (payload.schema_version !== OWNER_PORTFOLIO_SCHEMA_VERSION) {
    return portfolioError("unsupported_schema_version", expected);
  }
  if (payload.read_only !== true || payload.mutated !== false) {
    return portfolioError("mutation_authority_rejected", expected);
  }
  if (typeof payload.workspace_id !== "string" || !payload.workspace_id.trim()) {
    return portfolioError("workspace_id_missing", expected);
  }
  if (payload.workspace_id !== expected) return portfolioError("workspace_mismatch", expected);
  if (!Array.isArray(payload.items)) return portfolioError("items_not_array", expected);
  if (payload.items.length > MAX_PORTFOLIO_ITEMS) return portfolioError("items_exceed_limit", expected);

  const ignored: PortfolioIgnoredCounts = { ...NO_IGNORED };
  const active: string[] = [];
  const seenActive = new Set<string>();

  for (const raw of payload.items) {
    if (!isRecord(raw)) {
      ignored.malformedEntries += 1;
      continue;
    }
    const id = raw.candidate_id;
    if (!isStableCandidateId(id)) {
      ignored.invalidId += 1;
      continue;
    }
    if (!isItemStatus(raw.status)) {
      ignored.unknownStatus += 1;
      continue;
    }
    if (raw.status !== "active") {
      ignored.notActive += 1;
      continue;
    }
    if (seenActive.has(id)) {
      ignored.duplicateActiveRows += 1;
      continue;
    }
    seenActive.add(id);
    active.push(id);
  }

  const evidenceMode = parseEvidenceMode(payload.evidence_mode);
  const generatedAt = typeof payload.generated_at === "string" ? payload.generated_at : null;
  const expiresAt = typeof payload.expires_at === "string" ? payload.expires_at : null;
  const freshness = describeFreshness({ expiresAt, generatedAt, nowMs: ctx.nowMs });

  const draft = payload.draft_research;
  const reported = isRecord(draft) && typeof draft.eligible === "boolean";
  const eligible = reported && (draft as Record<string, unknown>).eligible === true;
  const eligibility = {
    reported,
    eligible,
    reasons: reported ? stringList((draft as Record<string, unknown>).reasons) : [],
    conflict: eligible && active.length < PORTFOLIO_REQUIRED_ACTIVE_CANDIDATES,
  };

  const qualifiers: SurfaceQualifier[] = [];
  if (evidenceMode === "fixture_only" || evidenceMode === "simulated") qualifiers.push("fixture");
  if (freshness.status === "stale") qualifiers.push("stale");
  if (ignored.invalidId > 0 || ignored.unknownStatus > 0 || ignored.malformedEntries > 0) {
    qualifiers.push("partial");
  }

  return {
    phase: active.length === 0 ? "empty" : "ready",
    qualifiers,
    reasons: [],
    workspaceId: expected,
    evidenceMode,
    activeCandidateIds: active,
    activeCount: active.length,
    required: PORTFOLIO_REQUIRED_ACTIVE_CANDIDATES,
    ignored,
    eligibility,
    freshness,
    generatedAt,
  };
}

/**
 * The ONE mapping from a fetch outcome to a portfolio model (used by the hook).
 * The expected workspace is always the one REQUESTED, never one taken from the
 * payload, so a response can only ever be shown for the workspace that asked.
 * `null` means the request is still in flight.
 */
export function resultToPortfolioModel(
  result: PortfolioFetchResult | null,
  ctx: { workspaceId: string | null; nowMs: number },
): PortfolioReviewModel {
  const workspaceId = ctx.workspaceId?.trim() ? ctx.workspaceId : null;
  if (!workspaceId) return portfolioUnavailable("workspace_not_selected");
  if (result === null) return portfolioLoading(workspaceId);
  if (result.kind === "ok") {
    return adaptPortfolioPayload(result.payload, { expectedWorkspaceId: workspaceId, nowMs: ctx.nowMs });
  }
  return result.kind === "unavailable"
    ? portfolioUnavailable(result.reason, workspaceId)
    : portfolioError(result.reason, workspaceId);
}

/**
 * Whether draft-research actions may be used. Every condition is required; the
 * backend must EXPLICITLY report eligibility, and no local count can substitute
 * for that. Returns every blocking reason so the UI can always say why.
 */
export function evaluateDraftResearchGate(
  portfolio: PortfolioReviewModel,
  options: { handlerConnected: boolean },
): DraftResearchGate {
  const reasons: string[] = [];

  if (portfolio.phase === "loading") reasons.push("The portfolio is still loading.");
  else if (portfolio.phase === "error") reasons.push("The portfolio could not be loaded.");
  else if (portfolio.phase === "unavailable") reasons.push("The portfolio read model is unavailable.");
  else {
    if (portfolio.qualifiers.includes("fixture")) {
      reasons.push("Fixture / simulation data cannot enable draft research.");
    }
    if (portfolio.qualifiers.includes("stale")) reasons.push("Portfolio evidence is stale.");
    if (portfolio.freshness.status === "invalid") {
      reasons.push("Portfolio freshness could not be verified (invalid date).");
    }
    if (portfolio.qualifiers.includes("partial")) {
      reasons.push("Some portfolio entries were ignored as invalid, so the portfolio cannot be trusted for drafting.");
    }
    if (portfolio.evidenceMode === "unknown") reasons.push("Portfolio provenance is not reported.");
    if (!portfolio.eligibility.reported) {
      reasons.push("The backend has not reported draft-research eligibility.");
    } else if (!portfolio.eligibility.eligible) {
      reasons.push("The backend reports this portfolio is not eligible for draft research.");
      reasons.push(...portfolio.eligibility.reasons);
    } else if (portfolio.eligibility.conflict) {
      const known = portfolio.activeCount === null ? "unknown" : String(portfolio.activeCount);
      reasons.push(
        `Backend eligibility conflicts with the distinct active candidate count (${known}/${portfolio.required}).`,
      );
    }
  }

  if (!options.handlerConnected) {
    reasons.push("No draft-research service is connected to this page yet.");
  }
  return { enabled: reasons.length === 0, reasons };
}
