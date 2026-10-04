import { joinApiPath, resolveApiBaseUrl } from "../../../lib/apiBase.ts";
import {
  OWNER_PERFORMANCE_API_PATH,
  type OwnerPerformanceReport,
} from "../contracts/ownerPerformanceReport.ts";
import { assertReportContract } from "./presentReport.ts";

export class OwnerPerformanceApiError extends Error {
  status?: number;
  constructor(message: string, status?: number) {
    super(message);
    this.name = "OwnerPerformanceApiError";
    this.status = status;
  }
}

export class OwnerPerformanceAuthError extends OwnerPerformanceApiError {
  constructor(status: number) {
    super("Authentication is required to view the owner performance report.", status);
    this.name = "OwnerPerformanceAuthError";
  }
}

export class OwnerPerformanceUnavailableError extends OwnerPerformanceApiError {
  constructor(reason?: string, status?: number) {
    const detail =
      reason ??
      "Backend route GET /api/owner/performance is not yet mounted. Contract dependency: owner-performance-report-v1 (PR #368).";
    super(detail, status);
    this.name = "OwnerPerformanceUnavailableError";
  }
}

/**
 * Consumes GET /api/owner/performance without a workspace selector.
 * Fails closed when the route is unmounted (404/503), unauthorized (401/403),
 * or returns non-contract data.
 */
export async function fetchOwnerPerformanceReport(
  fetchImpl: typeof fetch = fetch
): Promise<OwnerPerformanceReport> {
  const baseUrl = resolveApiBaseUrl();
  const url = joinApiPath(baseUrl, OWNER_PERFORMANCE_API_PATH);

  let response: Response;
  try {
    response = await fetchImpl(url, {
      method: "GET",
      headers: {
        Accept: "application/json",
      },
      credentials: "same-origin",
    });
  } catch {
    throw new OwnerPerformanceUnavailableError(
      `Network or server unreachable while calling ${OWNER_PERFORMANCE_API_PATH}. Contract dependency: owner-performance-report-v1 (PR #368).`
    );
  }

  if (response.status === 401 || response.status === 403) {
    throw new OwnerPerformanceAuthError(response.status);
  }

  if (response.status === 404 || response.status === 503) {
    throw new OwnerPerformanceUnavailableError(
      `Backend route GET ${OWNER_PERFORMANCE_API_PATH} unavailable (HTTP ${response.status}). Contract dependency: owner-performance-report-v1 (PR #368).`,
      response.status
    );
  }

  if (!response.ok) {
    throw new OwnerPerformanceApiError(
      `HTTP ${response.status} loading ${OWNER_PERFORMANCE_API_PATH}.`,
      response.status
    );
  }

  const json = (await response.json()) as unknown;
  return assertReportContract(json);
}
