import { usePhase1Readiness } from "@/hooks/useCanonicalEvents";
import {
  adaptPhase1DecisionReport,
  type Phase1ReadinessSource,
} from "../lib/adaptPhase1DecisionReport";
import type { Phase1DecisionReportView } from "../contracts/phase1DecisionReport";

/**
 * Page-local journey over the stable main contract GET /api/phase1/readiness.
 * Does not call public-market or other #422-owned surfaces.
 */
export function usePhase1DecisionReport(): Phase1DecisionReportView {
  const query = usePhase1Readiness();
  return adaptPhase1DecisionReport({
    isLoading: query.isLoading,
    isError: Boolean(query.error),
    errorMessage: query.error instanceof Error ? query.error.message : null,
    data: (query.data ?? null) as Phase1ReadinessSource | null,
  });
}
