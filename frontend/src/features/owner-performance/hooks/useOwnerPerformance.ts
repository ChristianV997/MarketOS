import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import type { DashboardPhase } from "../components/OwnerPerformanceDashboard.tsx";
import type { OwnerPerformanceReport } from "../contracts/ownerPerformanceReport.ts";
import {
  fetchOwnerPerformanceReport,
  OwnerPerformanceAuthError,
  OwnerPerformanceUnavailableError,
} from "../lib/fetchOwnerPerformance.ts";

export interface UseOwnerPerformanceOptions {
  enabled?: boolean;
}

export interface UseOwnerPerformanceResult {
  phase: DashboardPhase;
  report: OwnerPerformanceReport | null;
  errorMessage?: string;
  unavailableReason?: string;
  authMessage?: string;
  isStale: boolean;
  staleMessage?: string;
  refetch: () => void;
  isLoading: boolean;
}

export function useOwnerPerformance(
  options: UseOwnerPerformanceOptions = {}
): UseOwnerPerformanceResult {
  const query = useQuery<OwnerPerformanceReport, Error>({
    queryKey: ["owner-performance-report"],
    queryFn: () => fetchOwnerPerformanceReport(),
    enabled: options.enabled ?? true,
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });

  return useMemo(() => {
    if (query.isLoading) {
      return {
        phase: "loading",
        report: null,
        isStale: false,
        isLoading: true,
        refetch: query.refetch,
      };
    }

    if (query.isError) {
      const err = query.error;
      if (err instanceof OwnerPerformanceAuthError) {
        return {
          phase: "auth",
          report: null,
          authMessage: err.message,
          isStale: false,
          isLoading: false,
          refetch: query.refetch,
        };
      }
      if (err instanceof OwnerPerformanceUnavailableError) {
        return {
          phase: "unavailable",
          report: null,
          unavailableReason: err.message,
          isStale: false,
          isLoading: false,
          refetch: query.refetch,
        };
      }
      return {
        phase: "error",
        report: null,
        errorMessage: err.message ?? "The report could not be read.",
        isStale: false,
        isLoading: false,
        refetch: query.refetch,
      };
    }

    if (query.data) {
      const report = query.data;
      const isEmpty = (report.evidence_quality?.line_count ?? 0) === 0;
      const isStale = Boolean(query.isStale && query.dataUpdatedAt > 0);
      const staleTimeStr = query.dataUpdatedAt
        ? new Date(query.dataUpdatedAt).toLocaleTimeString()
        : "";
      return {
        phase: isEmpty ? "empty" : "ready",
        report,
        isStale,
        staleMessage: isStale
          ? `Cached report from ${staleTimeStr}. Data may be stale.`
          : undefined,
        isLoading: false,
        refetch: query.refetch,
      };
    }

    return {
      phase: "unavailable",
      report: null,
      unavailableReason:
        "Backend route GET /api/owner/performance is not yet mounted. Contract dependency: owner-performance-report-v1 (PR #368).",
      isStale: false,
      isLoading: false,
      refetch: query.refetch,
    };
  }, [
    query.isLoading,
    query.isError,
    query.error,
    query.data,
    query.isStale,
    query.dataUpdatedAt,
    query.refetch,
  ]);
}
