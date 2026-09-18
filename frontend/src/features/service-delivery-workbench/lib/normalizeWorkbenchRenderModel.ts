import type { ServiceEngagementProjection } from "../contracts/serviceEngagementProjection.ts";

/** Deterministic, secret-free snapshot. Preserves engagement order. Never ranks. */
export function normalizeWorkbenchRenderModel(projection: ServiceEngagementProjection) {
  return {
    schema_version: projection.schema_version,
    input_contract: projection.input_contract,
    availability: projection.availability,
    live_endpoint_status: projection.live_endpoint_status,
    read_only: projection.read_only,
    engagement_ids_in_order: projection.engagements.map((item) => item.engagement_id),
    lifecycle_in_order: projection.engagements.map((item) => item.lifecycle_state),
    evidence_classes_in_order: projection.engagements.map((item) =>
      item.evidence.map((entry) => entry.evidence_class),
    ),
    frontend_calculates: projection.engagements.every((item) => item.economics.frontend_calculates === false),
    diagnostics: [...projection.diagnostics],
  };
}
