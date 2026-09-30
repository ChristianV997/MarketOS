import type { OwnerLoadState, OwnerSourcePayload } from "../contracts/ownerDashboard.ts";

export interface QuerySnapshot {
  data: OwnerSourcePayload | undefined;
  isError: boolean;
}

/**
 * Data always wins over an error: a failed refresh keeps the last loaded data on
 * screen (flagged as such), while a failure with nothing loaded is "unavailable".
 */
export function loadStateFromQuery({ data, isError }: QuerySnapshot): OwnerLoadState {
  if (data) return { status: "success", payload: data };
  if (isError) return { status: "error", code: "source_unavailable" };
  return { status: "loading" };
}

export function refreshFailedFromQuery({ data, isError }: QuerySnapshot): boolean {
  return Boolean(data && isError);
}
