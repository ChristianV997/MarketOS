/**
 * Same-origin client for the PROPOSED live consulting research report route.
 *
 * - Uses `resolveApiBaseUrl` / `joinApiPath` from `frontend/src/lib/apiBase.ts`.
 * - Never persists tokens or reports in browser web storage.
 * - Never sends a client-chosen workspace_id as authority.
 * - Credentials: `same-origin` for cookie sessions; optional Bearer from an
 *   injected per-request token reader (token not retained).
 * - Missing route → `unavailable`; 401 → `unauthorized`; 403 → `forbidden`.
 * - `fetch` is injectable for contract tests (not live validation).
 */

import { joinApiPath, resolveApiBaseUrl } from "../../../lib/apiBase.ts";
import {
  LIVE_RESEARCH_REPORT_ENDPOINT,
  MAX_LIVE_RESEARCH_RESPONSE_CHARS,
  type LiveResearchReportRequestV1,
  type LiveResearchSession,
  type LiveResearchTransportKind,
} from "../contracts/liveResearchReport.ts";

export type LiveResearchFetchResult =
  | { kind: "ok"; status: number; payload: unknown }
  | { kind: Exclude<LiveResearchTransportKind, "ok" | "idle" | "loading">; reason: string; status?: number };

export interface LiveResearchFetchOptions {
  request: LiveResearchReportRequestV1;
  session?: LiveResearchSession | null;
  fetchImpl?: typeof fetch;
  baseUrl?: string;
  endpoint?: string;
  signal?: AbortSignal;
  /**
   * When true (default), skip the network if no session signal is present.
   * Production mounts have no AuthProvider today → auth_required.
   */
  requireSession?: boolean;
}

const ABSENT_STATUSES = new Set([404, 405, 501]);

export function buildLiveResearchReportUrl(
  options: Pick<LiveResearchFetchOptions, "baseUrl" | "endpoint"> = {},
): string {
  const base = options.baseUrl ?? resolveApiBaseUrl();
  return joinApiPath(base, options.endpoint ?? LIVE_RESEARCH_REPORT_ENDPOINT);
}

function sessionPresent(session: LiveResearchSession | null | undefined): boolean {
  if (!session) return false;
  if (session.hasCookieSession === true) return true;
  if (typeof session.getAccessToken === "function") return true;
  return false;
}

export async function fetchLiveResearchReport(
  options: LiveResearchFetchOptions,
): Promise<LiveResearchFetchResult> {
  const requireSession = options.requireSession !== false;
  if (requireSession && !sessionPresent(options.session)) {
    return { kind: "auth_required", reason: "session_provider_unavailable" };
  }

  if (!options.request.query?.trim()) {
    return { kind: "error", reason: "query_required" };
  }

  // Reject accidental client workspace authority fields if a caller stuffed them
  // onto the request object beyond the typed shape.
  const rawRequest = options.request as LiveResearchReportRequestV1 & {
    workspace_id?: unknown;
    workspaceId?: unknown;
  };
  if (rawRequest.workspace_id != null || rawRequest.workspaceId != null) {
    return { kind: "error", reason: "client_workspace_authority_rejected" };
  }

  const fetchImpl = options.fetchImpl ?? (typeof fetch === "function" ? fetch : undefined);
  if (!fetchImpl) return { kind: "unavailable", reason: "fetch_unavailable" };

  const headers: Record<string, string> = {
    Accept: "application/json",
    "Content-Type": "application/json",
  };

  if (options.session?.getAccessToken) {
    let token: string | null = null;
    try {
      token = await options.session.getAccessToken();
    } catch {
      return { kind: "auth_required", reason: "token_reader_failed" };
    }
    if (!token) return { kind: "auth_required", reason: "token_missing" };
    headers.Authorization = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetchImpl(buildLiveResearchReportUrl(options), {
      method: "POST",
      headers,
      credentials: "same-origin",
      body: JSON.stringify(options.request),
      signal: options.signal,
    });
  } catch (error) {
    const aborted = error instanceof Error && error.name === "AbortError";
    return { kind: "error", reason: aborted ? "request_aborted" : "network_error" };
  }

  if (response.status === 401) return { kind: "unauthorized", reason: "http_401", status: 401 };
  if (response.status === 403) return { kind: "forbidden", reason: "http_403", status: 403 };
  if (ABSENT_STATUSES.has(response.status)) {
    return { kind: "unavailable", reason: "endpoint_not_available", status: response.status };
  }
  if (response.status === 503) {
    return { kind: "unavailable", reason: "identity_or_service_unavailable", status: 503 };
  }
  if (!response.ok) return { kind: "error", reason: `http_${response.status}`, status: response.status };

  let text: string;
  try {
    text = await response.text();
  } catch {
    return { kind: "error", reason: "network_error", status: response.status };
  }
  if (text.length > MAX_LIVE_RESEARCH_RESPONSE_CHARS) {
    return { kind: "error", reason: "payload_too_large", status: response.status };
  }

  try {
    return { kind: "ok", status: response.status, payload: JSON.parse(text) as unknown };
  } catch {
    return { kind: "error", reason: "malformed_json", status: response.status };
  }
}
