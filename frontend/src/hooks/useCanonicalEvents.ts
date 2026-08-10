import { useQuery } from "@tanstack/react-query";
import { fetchCommerceRuns, fetchEventTimeline, fetchEvents, fetchEventsReadiness, fetchShopifyImports, type EventQueryParams } from "@/lib/canonicalEventsApi";

const key = (name: string, params?: EventQueryParams) => ["canonical-events", name, params ?? {}] as const;
const options = { staleTime: 30_000 };

export const useEventTimeline = (params: EventQueryParams) => useQuery({ queryKey: key("timeline", params), queryFn: () => fetchEventTimeline(params), ...options });
export const useEventRecords = (params: EventQueryParams) => useQuery({ queryKey: key("records", params), queryFn: () => fetchEvents(params), ...options });
export const useCommerceRuns = (params: EventQueryParams) => useQuery({ queryKey: key("commerce-runs", params), queryFn: () => fetchCommerceRuns(params), ...options });
export const useShopifyImports = (params: EventQueryParams) => useQuery({ queryKey: key("shopify-imports", params), queryFn: () => fetchShopifyImports(params), ...options });
export const useEventsReadiness = () => useQuery({ queryKey: key("readiness"), queryFn: fetchEventsReadiness, ...options });
