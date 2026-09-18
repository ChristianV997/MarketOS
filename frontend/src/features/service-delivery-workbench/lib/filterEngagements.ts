import type {
  EvidenceClass,
  LifecycleState,
  PriorityServiceId,
  ServiceEngagement,
} from "../contracts/serviceEngagementProjection.ts";

export type WorkbenchFilters = {
  query: string;
  serviceId: PriorityServiceId | "all";
  lifecycle: LifecycleState | "all";
  evidenceClass: EvidenceClass | "all";
};

export const EMPTY_FILTERS: WorkbenchFilters = {
  query: "",
  serviceId: "all",
  lifecycle: "all",
  evidenceClass: "all",
};

/**
 * Filter without mutating the source array or reordering server/fixture order.
 */
export function filterEngagements(
  engagements: readonly ServiceEngagement[],
  filters: WorkbenchFilters,
): ServiceEngagement[] {
  const query = filters.query.trim().toLowerCase();
  return engagements.filter((item) => {
    if (filters.serviceId !== "all" && item.service_id !== filters.serviceId) return false;
    if (filters.lifecycle !== "all" && item.lifecycle_state !== filters.lifecycle) return false;
    if (
      filters.evidenceClass !== "all"
      && !item.evidence.some((entry) => entry.evidence_class === filters.evidenceClass)
    ) {
      return false;
    }
    if (!query) return true;
    const haystack = [
      item.engagement_id,
      item.intake.display_name,
      item.intake.client_id,
      item.service_id,
      item.lifecycle_state,
      item.next_best_action.action,
    ].join(" ").toLowerCase();
    return haystack.includes(query);
  });
}
