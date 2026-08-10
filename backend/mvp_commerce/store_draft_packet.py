"""Store-draft export packet; Shopify remains one optional target."""
from __future__ import annotations
from .models import OpportunityCandidate, StoreDraftPacket


def build_store_draft_packet(candidate: OpportunityCandidate, target_platform: str = "shopify") -> StoreDraftPacket:
    return StoreDraftPacket(candidate.candidate_id, target_platform, candidate.product_name, f"Draft listing for {candidate.product_name}. Complete only with verified specifications and supplier information.", "Manual test collection", ("Variant placeholder: size/color only after supplier confirmation",),
        ("Primary product image", "Use-case image", "Specification image", "Packaging/fulfillment image"),
        ("Price is a dry-run assumption, not an approved store price.",), ("Inventory level is unknown.", "Stock synchronization is not configured."),
        ("Supplier identity, landed cost, shipping timing, reliability, duties, and returns are unknown.",),
        ("Create product draft manually", "Attach verified assets and copy", "Confirm inventory and policy data", "Obtain human approval before publishing"),
        ("shopify_product_creation", "inventory_mutation", "supplier_order", "fulfillment_action", "payment_action", "publish"))
