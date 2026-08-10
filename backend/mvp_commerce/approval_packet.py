"""Explicit human approval requirements for a Commerce MVP packet."""
from __future__ import annotations
import hashlib
from .models import ManualApprovalPacket, OpportunityCandidate


def build_manual_approval_packet(candidate: OpportunityCandidate, recommendations: tuple[dict, ...]) -> ManualApprovalPacket:
    approval_id = "commerce-approval-" + hashlib.sha256(candidate.candidate_id.encode()).hexdigest()[:16]
    return ManualApprovalPacket(approval_id, candidate.candidate_id,
        ("Evidence review: public signals are corroborated with supplier/customer research.", "Economics review: price, landed cost, fees, returns, and CAC assumptions are verified.", "Claim/compliance review: every publishable statement has product-specific support.", "Operator approval: a human explicitly approves any external store, creative, message, spend, or supplier action."),
        ("Approve one manual export target at a time.", "Record approver, timestamp, source evidence, and rollback owner."),
        ("launch", "spend", "publish", "shopify_mutate", "supplier_order", "inventory_mutate", "fulfillment", "payment", "refund", "customer_message"), recommendations,
        ("creative packet", "landing-page packet", "store-draft packet", "canonical event stream"),
        ("Resolve unknown supplier/cost data", "Select an approved manual export target", "Create drafts manually", "Return outcome evidence to MarketOS"),
        ("Public signals are not demand proof.", "All economics values are assumptions.", "This packet has no external authority."))
