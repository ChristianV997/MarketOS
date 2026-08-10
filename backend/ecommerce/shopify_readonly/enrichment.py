"""Optional, conservative Commerce MVP enrichment from read-only store context."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .models import ShopifyStoreContext


@dataclass(frozen=True)
class CommerceMvpEnrichmentReport:
    workspace_id: str
    batch_id: str
    candidate_id: str | None
    overlap_titles: tuple[str, ...]
    notes: tuple[str, ...]
    warnings: tuple[str, ...]
    store_context: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"workspace_id": self.workspace_id, "batch_id": self.batch_id, "candidate_id": self.candidate_id,
                "overlap_titles": list(self.overlap_titles), "notes": list(self.notes), "warnings": list(self.warnings),
                "store_context": self.store_context}


def find_candidate_store_overlap(candidate: Any, store_context: ShopifyStoreContext) -> tuple[str, ...]:
    if candidate is None: return ()
    tokens = {item.lower() for item in str(candidate.product_name).replace("-", " ").split() if len(item) > 2}
    return tuple(title for title in store_context.top_product_titles if tokens.intersection(title.lower().replace("-", " ").split()))


def build_shopify_context_notes(candidate: Any, store_context: ShopifyStoreContext) -> tuple[tuple[str, ...], tuple[str, ...]]:
    overlap = find_candidate_store_overlap(candidate, store_context)
    notes = [f"Read-only store context: {store_context.active_product_count} active products and {store_context.out_of_stock_variant_count} observed out-of-stock variants."]
    notes.append(f"Observed order context uses {', '.join(store_context.currency_set) or 'no recorded'} currency; AOV is historical context only, not a forecast.")
    notes.append("Existing similar product observed in supplied store export." if overlap else "No title-level overlap found in supplied store export; this is not evidence of absence or demand.")
    warnings = ["Shopify context is read-only, PII-redacted, and advisory. It does not change opportunity selection or authorize a launch."]
    return tuple(notes), tuple(warnings)


def enrich_commerce_mvp_with_shopify_context(commerce_run: Any, store_context: ShopifyStoreContext) -> tuple[Any, CommerceMvpEnrichmentReport]:
    candidate = getattr(commerce_run, "selected_candidate", None)
    overlap = find_candidate_store_overlap(candidate, store_context); notes, warnings = build_shopify_context_notes(candidate, store_context)
    report = CommerceMvpEnrichmentReport(commerce_run.workspace_id, store_context.batch_id, getattr(candidate, "candidate_id", None), overlap, notes, warnings, store_context.to_dict())
    metadata = dict(getattr(commerce_run, "metadata", {})); metadata["shopify_readonly_enrichment"] = report.to_dict()
    existing_warnings = tuple(getattr(commerce_run, "warnings", ())) + warnings
    return replace(commerce_run, metadata=metadata, warnings=existing_warnings), report


__all__ = ["CommerceMvpEnrichmentReport", "build_shopify_context_notes", "enrich_commerce_mvp_with_shopify_context", "find_candidate_store_overlap"]
