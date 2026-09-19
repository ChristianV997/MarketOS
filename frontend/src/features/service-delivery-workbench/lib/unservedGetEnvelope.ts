import { FUTURE_WORKBENCH_PATH } from "../contracts/serviceEngagementProjection.ts";

/** Fail-closed envelope used when GET is absent or the fetch throws. */
export const UNSERVED_GET_ENVELOPE = {
  schema_version: "service-engagement-projection-v1",
  availability: "unavailable",
  live_endpoint: FUTURE_WORKBENCH_PATH,
  live_endpoint_status: "unavailable",
  read_only: true,
  generated_at: "unserved",
  engagements: [],
  diagnostics: ["canonical_get_not_served"],
  input_contract: "unknown",
  network_calls: false,
  mutated: false,
} as const;
