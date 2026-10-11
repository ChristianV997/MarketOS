import { ApprovalLedgerReview } from "./components/ApprovalLedgerReview.tsx";
import { buildApprovalLedgerFixture } from "./fixtures/ledgerFixture.ts";

/**
 * Mountable page for offline Approval Ledger review.
 * Registered at `/operator/approval-ledger` via `frontend/src/main.tsx` under Shell.
 * Sidebar/nav ownership stays with the shell lane; this page is review-only.
 */
export function ApprovalLedgerReviewPage() {
  return <ApprovalLedgerReview packet={buildApprovalLedgerFixture()} />;
}
