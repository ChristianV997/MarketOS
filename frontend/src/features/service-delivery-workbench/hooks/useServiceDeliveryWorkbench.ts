import { useMemo, useState } from "react";
import { buildDemoProjection } from "../fixtures/buildFixtures.ts";
import { composeWorkbenchViewModel } from "../lib/composeWorkbenchViewModel.ts";
import { EMPTY_FILTERS, type WorkbenchFilters } from "../lib/filterEngagements.ts";

/**
 * Canonical GET /api/service-delivery/workbench is not on origin/main.
 * The hook never POSTs, never opens a second API client, and never treats
 * fixtures as live-validated commercial proof.
 */
export function useServiceDeliveryWorkbench() {
  const projection = useMemo(() => buildDemoProjection(), []);
  const [filters, setFilters] = useState<WorkbenchFilters>(EMPTY_FILTERS);
  const [selectedId, setSelectedId] = useState<string | null>(
    projection.engagements[0]?.engagement_id ?? null,
  );
  const [isLoading] = useState(false);

  const view = composeWorkbenchViewModel({
    isLoading,
    errorMessage: null,
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
    recovery: "Reload fixtures or clear filters. Live fetch remains unavailable until a canonical projection ships.",
  };
}
