import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import type { OwnerDashboardSource, OwnerDashboardViewModel } from "../contracts/ownerDashboard.ts";
import { composeOwnerDashboard } from "../lib/composeOwnerDashboard.ts";
import { loadStateFromQuery, refreshFailedFromQuery } from "../lib/loadState.ts";
import { fixtureSource } from "../sources/fixtureSource.ts";

export interface UseOwnerDashboardResult {
  viewModel: OwnerDashboardViewModel;
  retry: () => void;
  isRetrying: boolean;
}

export function useOwnerDashboard(source: OwnerDashboardSource = fixtureSource): UseOwnerDashboardResult {
  const query = useQuery({
    queryKey: ["owner-dashboard", source.id],
    queryFn: () => source.load(),
    retry: false,
    refetchOnWindowFocus: false,
  });

  const viewModel = useMemo(() => {
    const snapshot = { data: query.data, isError: query.isError };
    return composeOwnerDashboard({
      load: loadStateFromQuery(snapshot),
      dataMode: source.dataMode,
      nowMs: query.dataUpdatedAt || Date.now(),
      refreshFailed: refreshFailedFromQuery(snapshot),
    });
  }, [query.data, query.isError, query.dataUpdatedAt, source.dataMode]);

  return { viewModel, retry: () => void query.refetch(), isRetrying: query.isFetching && !query.isPending };
}
