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
# Matches backend.commerce.catalog.STATUS_LIVE. Draft/paused are catalog
# statuses but are not active inventory for this gate.
ACTIVE_STATUSES = frozenset({"live"})
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


def _row_identity(raw: Mapping[str, Any]) -> str | None:
    product_id = _well_formed_id(raw.get("product_id"))
    candidate_id = _well_formed_id(raw.get("candidate_id"))
    if product_id and candidate_id and product_id != candidate_id:
        return None
    return product_id or candidate_id


def _row_qualifies(raw: Mapping[str, Any]) -> tuple[bool, str]:
    status = raw.get("status")
    if status is None or status == "":
        return False, "status_missing"
    if not isinstance(status, str) or status not in ACTIVE_STATUSES:
        return False, "status_not_active"
    eligible_flag = raw.get("eligible")
    if eligible_flag is None:
        return False, "eligibility_unknown"
    if eligible_flag is not True:
        return False, "ineligible"
    return True, "qualifying"


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

    discarded: list[str] = []
    observations: dict[str, set[str]] = {}
    for index, raw in enumerate(inventory):
        if not isinstance(raw, Mapping):
            discarded.append(f"malformed_row:{index}")
            continue
        product_id = _row_identity(raw)
        if product_id is None:
            discarded.append(f"malformed_id:{index}")
            continue
        qualifies, code = _row_qualifies(raw)
        observations.setdefault(product_id, set()).add(code)
        if not qualifies:
            discarded.append(f"{code}:{product_id}")

    eligible_ids: list[str] = []
    for product_id in sorted(observations):
        codes = observations[product_id]
        if codes == {"qualifying"}:
            eligible_ids.append(product_id)
            continue
        if "qualifying" in codes:
            discarded.append(f"duplicate_conflict:{product_id}")

    eligible_ids_tuple = tuple(eligible_ids)
    count = len(eligible_ids_tuple)
    discarded_tuple = tuple(sorted(set(discarded)))
    if count >= MINIMUM_ELIGIBLE_PRODUCTS:
        return OwnerBrandPlanningGate(
            status="eligible",
            eligible=True,
            eligible_count=count,
            required_count=MINIMUM_ELIGIBLE_PRODUCTS,
            eligible_product_ids=eligible_ids_tuple,
            reasons=(),
            discarded=discarded_tuple,
        )
    reasons = ["insufficient_eligible_products"]
    if count == 0 and not inventory:
        reasons.append("inventory_empty")
    return OwnerBrandPlanningGate(
        status="blocked",
        eligible=False,
        eligible_count=count,
        required_count=MINIMUM_ELIGIBLE_PRODUCTS,
        eligible_product_ids=eligible_ids_tuple,
        reasons=tuple(reasons),
        discarded=discarded_tuple,
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
    "ACTIVE_STATUSES",
    "GATE_VERSION",
    "MINIMUM_ELIGIBLE_PRODUCTS",
    "OwnerBrandPlanningGate",
    "OwnerBrandPlanningGateError",
    "evaluate_owner_brand_planning_gate",
]
