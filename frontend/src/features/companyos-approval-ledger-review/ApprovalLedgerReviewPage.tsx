import { ApprovalLedgerReview } from "./components/ApprovalLedgerReview.tsx";
import { buildApprovalLedgerFixture } from "./fixtures/ledgerFixture.ts";

/**
 * Mountable page for offline Approval Ledger review.
 * Not registered in the shared router/Sidebar by this lane (Agent C owns nav).
 */
export function ApprovalLedgerReviewPage() {
  return <ApprovalLedgerReview packet={buildApprovalLedgerFixture()} />;
}
