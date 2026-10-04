/**
 * Read-only browser client for the PROPOSED owner portfolio read model.
 *
 * - GET only; never sends a body, never mutates.
 * - API origin comes from `frontend/src/lib/apiBase.ts` (the sole authority);
 *   this file does not read env vars or hard-code a host.
 * - A missing route (404/405/501) is `unavailable`, NOT an empty portfolio.
 * - `fetch` is injectable so the adapter is testable without a network.
 */

import { joinApiPath, resolveApiBaseUrl } from "../../../lib/apiBase";
import { OWNER_PORTFOLIO_ENDPOINT } from "../contracts/ownerResearch";

export type PortfolioFetchResult =
  | { kind: "ok"; payload: unknown }
  | { kind: "unavailable"; reason: string }
  | { kind: "error"; reason: string };

export interface PortfolioFetchOptions {
  workspaceId: string | null;
  fetchImpl?: typeof fetch;
  /** Overrides the base resolved from apiBase.ts (tests only). */
  baseUrl?: string;
  /** Overrides the proposed endpoint path. */
  endpoint?: string;
  signal?: AbortSignal;
}

/** Bound the body we are willing to parse. The contract caps items at 500. */
export const MAX_PORTFOLIO_RESPONSE_CHARS = 1_000_000;

const ABSENT_STATUSES = new Set([404, 405, 501]);

export function buildPortfolioUrl(workspaceId: string, options: Pick<PortfolioFetchOptions, "baseUrl" | "endpoint"> = {}): string {
  const base = options.baseUrl ?? resolveApiBaseUrl();
  const path = joinApiPath(base, options.endpoint ?? OWNER_PORTFOLIO_ENDPOINT);
  return `${path}?workspace_id=${encodeURIComponent(workspaceId)}`;
}

export async function fetchOwnerPortfolioPayload(options: PortfolioFetchOptions): Promise<PortfolioFetchResult> {
  const workspaceId = options.workspaceId?.trim() ? options.workspaceId : null;
  if (!workspaceId) return { kind: "unavailable", reason: "workspace_not_selected" };

  const fetchImpl = options.fetchImpl ?? (typeof fetch === "function" ? fetch : undefined);
  if (!fetchImpl) return { kind: "unavailable", reason: "fetch_unavailable" };

  let response: Response;
  try {
    response = await fetchImpl(buildPortfolioUrl(workspaceId, options), {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: options.signal,
    });
  } catch (error) {
    const aborted = error instanceof Error && error.name === "AbortError";
    return { kind: "error", reason: aborted ? "request_aborted" : "network_error" };
  }

  if (ABSENT_STATUSES.has(response.status)) {
    return { kind: "unavailable", reason: "endpoint_not_available" };
  }
  if (!response.ok) return { kind: "error", reason: `http_${response.status}` };

  let text: string;
  try {
    text = await response.text();
  } catch {
    return { kind: "error", reason: "network_error" };
  }
  if (text.length > MAX_PORTFOLIO_RESPONSE_CHARS) return { kind: "error", reason: "payload_too_large" };

  try {
    return { kind: "ok", payload: JSON.parse(text) as unknown };
  } catch {
    return { kind: "error", reason: "malformed_json" };
  }
}
