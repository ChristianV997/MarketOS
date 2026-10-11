import type { ApprovalLedgerViewModel, SurfaceState } from "../contracts/approvalLedger.ts";
import { humanizeToken } from "./safeText.ts";

export interface ApprovalLedgerSurfaceView {
  state: SurfaceState;
  message: string;
  model: ApprovalLedgerViewModel;
  selectedApprovalId: string | null;
  selectedRequest: ApprovalLedgerViewModel["requests"][number] | null;
  blockedPolicies: ApprovalLedgerViewModel["policies"];
  reviewablePolicies: ApprovalLedgerViewModel["policies"];
  authorityNote: string;
}

export function requestIds(model: ApprovalLedgerViewModel): string[] {
  return model.requests.map((item) => item.approval_id);
}

export function moveSelection(
  ids: string[],
  current: string | null,
  key: string,
): string | null {
  if (!ids.length) return null;
  const index = current == null ? -1 : ids.indexOf(current);
  if (key === "Home") return ids[0] ?? null;
  if (key === "End") return ids[ids.length - 1] ?? null;
  if (key === "ArrowDown") return ids[Math.min(ids.length - 1, Math.max(0, index + 1))] ?? null;
  if (key === "ArrowUp") return ids[Math.max(0, index <= 0 ? 0 : index - 1)] ?? null;
  return current;
}

export function composeApprovalLedgerView(input: {
  loading: boolean;
  errorMessage: string | null;
  model: ApprovalLedgerViewModel;
  rejected: boolean;
  selectedApprovalId: string | null;
}): ApprovalLedgerSurfaceView {
  const authorityNote =
    "Planning record only. Policy state, simulations, and decisions on this page do not authorize spend, publish, orders, payments, messaging, or provider calls.";

  if (input.loading) {
    return {
      state: "loading",
      message: "Loading CompanyOS Approval Ledger report…",
      model: input.model,
      selectedApprovalId: null,
      selectedRequest: null,
      blockedPolicies: [],
      reviewablePolicies: [],
      authorityNote,
    };
  }

  if (input.errorMessage || input.rejected) {
    return {
      state: "error",
      message: input.errorMessage
        || "Approval Ledger report rejected or unavailable. No decisions were invented.",
      model: input.model,
      selectedApprovalId: null,
      selectedRequest: null,
      blockedPolicies: [],
      reviewablePolicies: [],
      authorityNote,
    };
  }

  const blockedPolicies = input.model.policies.filter((item) => item.blocked_in_current_mode);
  const reviewablePolicies = input.model.policies.filter((item) => !item.blocked_in_current_mode);

  if (input.model.requests.length === 0 && input.model.policies.length === 0) {
    return {
      state: "empty",
      message: "No approval requests or policies in this offline report. Empty is not approval.",
      model: input.model,
      selectedApprovalId: null,
      selectedRequest: null,
      blockedPolicies,
      reviewablePolicies,
      authorityNote,
    };
  }

  const ids = requestIds(input.model);
  const selectedApprovalId = input.selectedApprovalId && ids.includes(input.selectedApprovalId)
    ? input.selectedApprovalId
    : ids[0] ?? null;
  const selectedRequest = input.model.requests.find((item) => item.approval_id === selectedApprovalId) ?? null;

  const queueBits = [
    `${input.model.queue_summary.blocked} blocked`,
    `${input.model.queue_summary.pending} pending review`,
    `${input.model.queue_summary.draft_or_simulated} draft or simulated`,
    `${input.model.queue_summary.approved} approved records (not live authority)`,
  ].join(" · ");

  return {
    state: "success",
    message: `Offline ledger loaded. ${queueBits}. ${humanizeToken(input.model.next_best_action)}`,
    model: input.model,
    selectedApprovalId,
    selectedRequest,
    blockedPolicies,
    reviewablePolicies,
    authorityNote,
  };
}
