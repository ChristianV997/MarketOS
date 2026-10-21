/**
 * Typed handoff for an authenticated, workspace-scoped live Market Research
 * report. PROPOSED — no route on main serves this contract today.
 *
 * Backend dependency (exact):
 * 1. Mount a FastAPI route at `LIVE_RESEARCH_REPORT_ENDPOINT` that composes
 *    `services.market_research.build_market_research_report` (or returns an
 *    already-shaped `consulting-research-surface-v1` packet).
 * 2. Gate with `require_principal` / `resolve_workspace_access` from
 *    `backend/identity/http.py`. Workspace authority MUST come from the
 *    verified principal (optional `X-MarketOS-Workspace` membership selector
 *    only). Reject body/query `workspace_id` as client authority.
 * 3. Deploy identity wiring (`get_token_verifier`, `get_workspace_repository`);
 *    until then gated routes fail closed as 503.
 *
 * This frontend never stores bearer tokens, never treats query-string
 * workspace ids as authority, and never upgrades fixture/demo packets to live.
 */

import { RESEARCH_SURFACE_VERSION } from "./researchSurface.ts";
import { MARKET_RESEARCH_REPORT_VERSION } from "../lib/mapMarketResearchReport.ts";

/** Proposed same-origin path. Absent (404/405/501) → `unavailable`, not success. */
export const LIVE_RESEARCH_REPORT_ENDPOINT = "/api/consulting-research/report" as const;

export const LIVE_RESEARCH_REQUEST_VERSION = "consulting-live-research-request-v1" as const;

/** Bound the JSON body we are willing to parse from a live response. */
export const MAX_LIVE_RESEARCH_RESPONSE_CHARS = 512 * 1024;

export const LIVE_RESEARCH_REPORT_VERSIONS = [
  RESEARCH_SURFACE_VERSION,
  MARKET_RESEARCH_REPORT_VERSION,
] as const;

export type LiveResearchReportVersion = (typeof LIVE_RESEARCH_REPORT_VERSIONS)[number];

/**
 * Operator-facing request fields. Workspace is intentionally omitted: the
 * server must resolve it from the authenticated session.
 */
export interface LiveResearchReportRequestV1 {
  request_version: typeof LIVE_RESEARCH_REQUEST_VERSION;
  /** Product / candidate query string. */
  query: string;
  category?: string | null;
  geography?: string | null;
  language?: string | null;
  /** Free-text buyer context; never treated as credentials. */
  buyer_context?: string | null;
  candidate_id?: string | null;
}

export type LiveResearchTransportKind =
  | "idle"
  | "loading"
  | "auth_required"
  | "unauthorized"
  | "forbidden"
  | "unavailable"
  | "error"
  | "ok";

export type LiveResearchSourceStatus = "collected" | "missing" | "partial" | "stale" | "unavailable";

/** Normalized per-source row for the operational panel (display only). */
export interface LiveResearchSourceObservation {
  source_id: string;
  label: string;
  status: LiveResearchSourceStatus;
  observed_at: string | null;
  provenance: string | null;
  detail: string | null;
}

/**
 * Optional injected session. MarketOS has no production AuthProvider today;
 * when absent the surface stays `auth_required` and does not call the network.
 * Tokens are read per request by the host and must not be persisted here.
 */
export interface LiveResearchSession {
  /** Opaque access token for Authorization header, if the host uses Bearer. */
  getAccessToken?: () => Promise<string | null>;
  /** True when a same-origin cookie session is believed present. */
  hasCookieSession?: boolean;
}

export function buildLiveResearchRequest(input: {
  query: string;
  category?: string;
  geography?: string;
  language?: string;
  buyer_context?: string;
  candidate_id?: string;
}): LiveResearchReportRequestV1 {
  return {
    request_version: LIVE_RESEARCH_REQUEST_VERSION,
    query: input.query.trim(),
    category: input.category?.trim() || null,
    geography: input.geography?.trim() || null,
    language: input.language?.trim() || null,
    buyer_context: input.buyer_context?.trim() || null,
    candidate_id: input.candidate_id?.trim() || null,
  };
}

export function liveResearchBoundaryCopy(kind: LiveResearchTransportKind, reason?: string | null): {
  title: string;
  body: string;
} {
  switch (kind) {
    case "auth_required":
      return {
        title: "Authentication required",
        body:
          reason === "session_provider_unavailable"
            ? "No verified session provider is mounted in this app. Live research stays blocked until an authenticated session and a gated report route exist. Demo/fixture packets are not live evidence."
            : "Sign in with a verified session to request live research. Demo/fixture packets are not live evidence.",
      };
    case "unauthorized":
      return {
        title: "Unauthorized",
        body: "The session was rejected (401). Live research was not loaded. Demo/fixture mode was not activated.",
      };
    case "forbidden":
      return {
        title: "Forbidden",
        body: "This session cannot access live research for the resolved workspace (403). Demo/fixture mode was not activated.",
      };
    case "unavailable":
      return {
        title: "Live research unavailable",
        body:
          reason === "endpoint_not_available"
            ? `No authenticated route serves ${LIVE_RESEARCH_REPORT_ENDPOINT} yet. Backend must expose a principal-gated Market Research report before this panel can show operational results.`
            : "Live research is unavailable. Demo/fixture packets are not substituted automatically.",
      };
    case "error":
      return {
        title: "Live research request failed",
        body: "The request failed safely. Payload contents are not shown. Demo/fixture mode was not activated.",
      };
    case "loading":
      return {
        title: "Requesting live research",
        body: "Waiting for the authenticated report response. No fixture fallback runs during this request.",
      };
    case "ok":
      return {
        title: "Live research response",
        body: "Server-backed packet for review only. Still draft; not launch authorization.",
      };
    case "idle":
    default:
      return {
        title: "Live research idle",
        body: "Submit a candidate query to request an authenticated report. Local JSON import is not the operational path.",
      };
  }
}
