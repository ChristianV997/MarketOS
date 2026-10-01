"""Route-neutral gate for owner brand/site planning.

Planning may begin only when at least three distinct, eligible product IDs
are present in the supplied inventory snapshot.  This module does not load
catalog.json, rank products, persist state, or create brands.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

GATE_VERSION = "owner-brand-planning-gate-v1"
MINIMUM_ELIGIBLE_PRODUCTS = 3
INELIGIBLE_STATUSES = frozenset({"archived", "inactive", "removed", "paused"})
_ID_MAX = 128


class OwnerBrandPlanningGateError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _well_formed_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if not value or value != value.strip():
        return None
    if len(value) > _ID_MAX:
        return None
    if any(ord(char) < 32 for char in value):
        return None
    return value


def evaluate_owner_brand_planning_gate(
    inventory: Sequence[Mapping[str, Any]] | None,
) -> "OwnerBrandPlanningGate":
    """Decide whether brand/site planning is unblocked.

    ``inventory`` must already carry server-derived eligibility.  A missing
    snapshot is not the same as zero eligible products.
    """
    if inventory is None:
        return OwnerBrandPlanningGate(
            status="blocked",
            eligible=False,
            eligible_count=None,
            required_count=MINIMUM_ELIGIBLE_PRODUCTS,
            eligible_product_ids=(),
            reasons=("inventory_missing",),
            discarded=("inventory_missing",),
        )
    if not isinstance(inventory, (list, tuple)):
        raise OwnerBrandPlanningGateError("inventory_must_be_sequence")

    eligible_ids: list[str] = []
    seen_eligible: set[str] = set()
    discarded: list[str] = []
    for index, raw in enumerate(inventory):
        if not isinstance(raw, Mapping):
            discarded.append(f"malformed_row:{index}")
            continue
        product_id = _well_formed_id(raw.get("product_id") or raw.get("candidate_id"))
        if product_id is None:
            discarded.append(f"malformed_id:{index}")
            continue
        status = raw.get("status")
        if isinstance(status, str) and status in INELIGIBLE_STATUSES:
            discarded.append(f"ineligible_status:{product_id}")
            continue
        eligible_flag = raw.get("eligible")
        if eligible_flag is None:
            discarded.append(f"eligibility_unknown:{product_id}")
            continue
        if eligible_flag is not True:
            discarded.append(f"ineligible:{product_id}")
            continue
        if product_id in seen_eligible:
            discarded.append(f"duplicate_id:{product_id}")
            continue
        seen_eligible.add(product_id)
        eligible_ids.append(product_id)

    eligible_ids = tuple(sorted(eligible_ids))
    count = len(eligible_ids)
    if count >= MINIMUM_ELIGIBLE_PRODUCTS:
        return OwnerBrandPlanningGate(
            status="eligible",
            eligible=True,
            eligible_count=count,
            required_count=MINIMUM_ELIGIBLE_PRODUCTS,
            eligible_product_ids=eligible_ids,
            reasons=(),
            discarded=tuple(sorted(set(discarded))),
        )
    reasons = ["insufficient_eligible_products"]
    if count == 0 and not inventory:
        reasons.append("inventory_empty")
    return OwnerBrandPlanningGate(
        status="blocked",
        eligible=False,
        eligible_count=count,
        required_count=MINIMUM_ELIGIBLE_PRODUCTS,
        eligible_product_ids=eligible_ids,
        reasons=tuple(reasons),
        discarded=tuple(sorted(set(discarded))),
    )


@dataclass(frozen=True)
class OwnerBrandPlanningGate:
    status: str
    eligible: bool
    eligible_count: int | None
    required_count: int
    eligible_product_ids: tuple[str, ...]
    reasons: tuple[str, ...]
    discarded: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": GATE_VERSION,
            "status": self.status,
            "eligible": self.eligible,
            "eligible_count": self.eligible_count,
            "required_count": self.required_count,
            "eligible_product_ids": list(self.eligible_product_ids),
            "reasons": list(self.reasons),
            "discarded": list(self.discarded),
            "planning_only": True,
            "creates_brand": False,
            "publishes": False,
            "launches_ads": False,
        }


__all__ = [
    "GATE_VERSION",
    "MINIMUM_ELIGIBLE_PRODUCTS",
    "OwnerBrandPlanningGate",
    "OwnerBrandPlanningGateError",
    "evaluate_owner_brand_planning_gate",
]
