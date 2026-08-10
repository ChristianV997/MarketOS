"""Validation for explicitly requested Supabase staging event persistence."""
from __future__ import annotations

import re
from typing import Any, Sequence

from backend.contracts.events import Event


class SupabaseEventValidationError(ValueError):
    """Raised when an event is unsafe or incomplete for staging persistence."""


_SHOPIFY_PREFIX = "shopify_"
_COMMERCE_PREFIX = "commerce_mvp_"
_AUTHORITY = {"dry_run", "advisory", "non_authoritative"}
_COMMERCE_AUTHORITY = _AUTHORITY | {"manual_approval_required", "no_launch_authority", "no_spend_authority", "no_publish_authority", "no_store_mutation_authority", "no_payment_authority", "no_fulfillment_authority"}
_SHOPIFY_AUTHORITY = _AUTHORITY | {"read_only", "pii_redacted", "no_mutation", "no_publish_authority", "no_store_mutation_authority", "no_inventory_mutation_authority", "no_fulfillment_authority", "no_payment_authority", "no_refund_authority", "no_customer_message_authority"}
_PII_KEYS = {"email", "phone", "address", "addresses", "default_address", "first_name", "last_name", "name"}
_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")


def assert_no_plain_pii_in_event(event: Event) -> None:
    """Reject direct identifiers in Shopify staging payloads, before any write."""
    if not event.event_type.startswith(_SHOPIFY_PREFIX): return
    def inspect(value: Any, path: str = "payload") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in _PII_KEYS:
                    raise SupabaseEventValidationError(f"plain PII key forbidden in Shopify staging event: {path}.{key}")
                inspect(item, f"{path}.{key}")
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value): inspect(item, f"{path}[{index}]")
        elif isinstance(value, str) and _EMAIL.search(value):
            raise SupabaseEventValidationError(f"plain email forbidden in Shopify staging event: {path}")
    inspect(event.payload)


def validate_event_for_supabase(event: Event) -> dict[str, Any]:
    if not isinstance(event, Event): raise SupabaseEventValidationError("Supabase staging requires a canonical Event")
    if not event.workspace_id: raise SupabaseEventValidationError("Supabase staging events require workspace_id")
    if not event.event_id or not event.event_type or not event.replay_hash(): raise SupabaseEventValidationError("event_id, event_type, and replay hash are required")
    required = _COMMERCE_AUTHORITY if event.event_type.startswith(_COMMERCE_PREFIX) else _SHOPIFY_AUTHORITY if event.event_type.startswith(_SHOPIFY_PREFIX) else set()
    missing = sorted(key for key in required if event.metadata.get(key) is not True)
    if missing: raise SupabaseEventValidationError(f"advisory authority metadata missing: {', '.join(missing)}")
    assert_no_plain_pii_in_event(event)
    return {"event_id": event.event_id, "replay_hash": event.replay_hash(), "valid": True}


def validate_events_for_supabase(events: Sequence[Event]) -> list[dict[str, Any]]:
    return [validate_event_for_supabase(event) for event in events]


def event_to_supabase_row(event: Event) -> dict[str, Any]:
    validate_event_for_supabase(event)
    return event.to_dict()


__all__ = ["SupabaseEventValidationError", "assert_no_plain_pii_in_event", "event_to_supabase_row", "validate_event_for_supabase", "validate_events_for_supabase"]
