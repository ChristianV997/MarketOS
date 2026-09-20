import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FUTURE_WORKBENCH_PATH } from "../contracts/serviceEngagementProjection.ts";
import { adaptServiceProjection } from "../lib/adaptServiceProjection.ts";
import { composeWorkbenchViewModel } from "../lib/composeWorkbenchViewModel.ts";
import { EMPTY_FILTERS, type WorkbenchFilters } from "../lib/filterEngagements.ts";
import { UNSERVED_GET_ENVELOPE } from "../lib/unservedGetEnvelope.ts";
import { joinApiPath, resolveApiBaseUrl } from "@/lib/apiBase";

/**
 * Probes the canonical GET with the #213 apiBase helper. Never POSTs.
 * A missing or failed route stays unavailable; demo fixtures are never substituted.
 */
async function probeWorkbenchProjection(): Promise<unknown> {
  const url = joinApiPath(resolveApiBaseUrl(), FUTURE_WORKBENCH_PATH);
  const response = await fetch(url, { method: "GET" });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    if (body && typeof body === "object") return body;
    throw new Error(`${response.status} ${FUTURE_WORKBENCH_PATH}`);
  }
  return response.json();
}

export function useServiceDeliveryWorkbench() {
  const probe = useQuery({
    queryKey: ["service-delivery-workbench-projection"],
    queryFn: probeWorkbenchProjection,
    retry: false,
    refetchOnWindowFocus: false,
  });

  const adapted = useMemo(() => {
    if (probe.data) {
      return adaptServiceProjection(probe.data, "live-get");
    }
    return adaptServiceProjection(UNSERVED_GET_ENVELOPE, "unavailable");
  }, [probe.data]);

  const projection = adapted.projection;
  const [filters, setFilters] = useState<WorkbenchFilters>(EMPTY_FILTERS);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const view = composeWorkbenchViewModel({
    isLoading: probe.isLoading,
    errorMessage: adapted.rejected
      ? adapted.rejection_reason
      : probe.isError
        ? `Canonical ${FUTURE_WORKBENCH_PATH} unavailable (${probe.error instanceof Error ? probe.error.message : "error"}). This is not a fixture success state.`
        : null,
    projection,
    filters,
    selectedId,
  });

  return {
    projection,
    filters,
    setFilters,
    selectedId: view.selected?.engagement_id ?? selectedId,
    setSelectedId,
    view,
    recovery: "Reload after a canonical GET /api/service-delivery/workbench envelope is served. Demo fixtures are not substituted when the route is down.",
  };
}
