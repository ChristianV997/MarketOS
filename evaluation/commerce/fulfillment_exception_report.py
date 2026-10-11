"""Offline fulfillment-exception review. Read-only; it does not act.

The canonical post-purchase lifecycle remains
``evaluation.commerce.fulfillment_risk_lifecycle``. This module does not copy
that transition table, invent a second event model, or recalculate money.
It explains whether a recorded path is legal, whether evidence is simulated
or fresh enough to read, and which orders need a human to look. It never
refunds, contacts a customer, submits a supplier order, or appends events.

OSS reviewed and not imported: python-statemachine 3.2.0 (MIT; transition
actions and the June 2026 SCXML advisory), pytransitions (MIT; callback side
effects), and Temporal's human-signal pause pattern (docs only). MarketOS
already has one fulfillment transition authority, ``Event``, and
``EventRepository``. No third-party source or dependency was added.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from backend.contracts.events import Event
from backend.events.repository import EventRepository

from evaluation.commerce.fulfillment_risk_lifecycle import (
    FULFILLMENT_STATES,
    LEGACY_STAGE_MAP,
    MAX_STATE_COUNT,
    SCENARIO_NAMES,
    FixtureFulfillmentAdapter,
    FulfillmentPortBundle,
    FulfillmentRiskScenario,
    _TRANSITIONS,
    build_named_adapter,
    build_named_scenario,
    run_fulfillment_risk_dry_run,
)

SCHEMA = "MarketOS.FulfillmentExceptionReview.v1"
DEFAULT_EVIDENCE_MAX_AGE_HOURS = 168
MAX_QUEUE = 32
MAX_READS = MAX_STATE_COUNT + 2
MAX_INVALID_EDGES = 8
MAX_REPORT_BYTES = 64 * 1024
_SIMULATED = frozenset({"fixture", "simulated", "assumed", "derived"})
_OBSERVED = frozenset({"observed", "live_readonly", "verified"})
_UNUSABLE = frozenset({"missing", "unknown", "stale", "rejected"})
_REFUND_VISIBLE = frozenset({"refund_requested", "refund_completed", "chargeback_opened", "chargeback_resolved"})
_FORBIDDEN_MARKERS = ("api_key", "access_token", "authorization", "password", "secret", "-----begin", "<html")
_SECRET_SHAPED = re.compile(
    r"(?i)(ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-(?:live|test)?-?[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|bearer [A-Za-z0-9._-]{10,})"
)
PROHIBITED_ACTIONS = (
    "refund",
    "customer_contact",
    "supplier_order_submit",
    "event_append",
    "order_mutation",
)
_FRESHNESS_RANK = {
    "freshness_inconsistent": 0,
    "expired": 1,
    "stale_for_review": 2,
    "freshness_unknown": 3,
    "not_observed": 4,
    "fresh": 5,
    "not_evaluated": 6,
}


def _reject_unsafe(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError(f"invalid {field_name}")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"invalid {field_name}")
    if any(marker in value.lower() for marker in _FORBIDDEN_MARKERS) or _SECRET_SHAPED.search(value):
        raise ValueError("unsafe review input")
    return value


def _require_reviewed_at(value: str) -> datetime:
    _reject_unsafe(value, "reviewed_at")
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        raise ValueError("invalid reviewed_at") from None
    if parsed.tzinfo is None:
        raise ValueError("reviewed_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def _optional_instant(value: str) -> datetime | None:
    if not value:
        return None
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _bound_age(hours: int) -> int:
    if not isinstance(hours, int) or isinstance(hours, bool) or hours < 1 or hours > 24 * 365:
        raise ValueError("invalid max_evidence_age_hours")
    return hours


def _canonical_transitions() -> Mapping[str, frozenset[str]]:
    if not isinstance(_TRANSITIONS, Mapping):
        raise ValueError("canonical fulfillment transitions are unavailable")
    return _TRANSITIONS


def _transitions_from(state: str) -> tuple[str, ...]:
    allowed = _canonical_transitions().get(state)
    if not isinstance(allowed, (set, frozenset, tuple, list)):
        return ()
    return tuple(sorted(item for item in allowed if isinstance(item, str)))


def explain_state_path(state_path: Sequence[str]) -> dict[str, Any]:
    """Explain a path against the canonical lifecycle table. Does not advance it."""
    if not isinstance(state_path, (tuple, list)):
        raise ValueError("invalid state_path")
    if len(state_path) > MAX_STATE_COUNT:
        return {
            "valid": False,
            "steps": [],
            "invalid_edges": [],
            "reasons": ["path_too_long"],
            "current_state": None,
            "lifecycle_allowed_next": [],
        }
    reasons: list[str] = []
    steps: list[dict[str, Any]] = []
    invalid_edges: list[dict[str, Any]] = []
    if not state_path:
        reasons.append("empty_path")
    elif state_path[0] != "order_received":
        reasons.append("path_not_started")
    for state in state_path:
        if not isinstance(state, str) or state not in FULFILLMENT_STATES:
            reasons.append("unknown_state")
            break
    table = _canonical_transitions()
    for previous, current in zip(state_path, state_path[1:]):
        if not isinstance(previous, str) or not isinstance(current, str):
            reasons.append("unknown_state")
            break
        allowed = table.get(previous)
        legal = isinstance(allowed, (set, frozenset, tuple, list)) and current in allowed
        step = {
            "from": previous if isinstance(previous, str) else "",
            "to": current if isinstance(current, str) else "",
            "valid": legal and previous in FULFILLMENT_STATES and current in FULFILLMENT_STATES,
            "legacy_stage": LEGACY_STAGE_MAP.get(current) if current in FULFILLMENT_STATES else None,
        }
        steps.append(step)
        if not step["valid"] and len(invalid_edges) < MAX_INVALID_EDGES:
            invalid_edges.append({
                "from": step["from"],
                "to": step["to"],
                "lifecycle_allowed_next": list(_transitions_from(previous) if previous in FULFILLMENT_STATES else ()),
            })
            reasons.append("invalid_transition")
    if "unknown_state" in reasons or "invalid_transition" in reasons or "empty_path" in reasons or "path_not_started" in reasons:
        valid = False
    else:
        valid = bool(state_path)
    current = state_path[-1] if state_path and isinstance(state_path[-1], str) and state_path[-1] in FULFILLMENT_STATES else None
    return {
        "valid": valid,
        "steps": steps,
        "invalid_edges": invalid_edges,
        "reasons": sorted(set(reasons)),
        "current_state": current,
        "lifecycle_allowed_next": list(_transitions_from(current)) if current and valid else [],
    }


def _ref_freshness(ref: Any, reviewed: datetime, max_age_hours: int) -> str:
    state = getattr(ref, "evidence_state", "unknown")
    captured = _optional_instant(getattr(ref, "captured_at", "") or "")
    valid_until = getattr(ref, "valid_until", "") or ""
    if state in _SIMULATED:
        return "not_observed"
    if state in _UNUSABLE:
        return "stale_for_review" if state == "stale" else "freshness_unknown"
    if state not in _OBSERVED:
        return "freshness_unknown"
    if captured is None:
        return "freshness_unknown"
    if captured > reviewed:
        return "freshness_inconsistent"
    expires = _optional_instant(valid_until) if valid_until else None
    if valid_until and expires is None:
        return "freshness_unknown"
    if expires is not None and expires < reviewed:
        return "expired"
    age_hours = (reviewed - captured).total_seconds() / 3600
    if age_hours > max_age_hours:
        return "stale_for_review"
    return "fresh"


def _evidence_summary(refs: Sequence[Any], reviewed: datetime, max_age_hours: int, *, evaluated: bool) -> dict[str, Any]:
    if not evaluated:
        return {"basis": "not_evaluated", "freshness": "not_evaluated", "states": []}
    states = sorted({getattr(ref, "evidence_state", "unknown") for ref in refs} or {"unknown"})
    if any(state in _OBSERVED for state in states) and any(state in _SIMULATED for state in states):
        basis = "mixed"
    elif states and all(state in _OBSERVED for state in states):
        basis = "observed"
    elif any(state in _SIMULATED for state in states):
        basis = "simulated"
    else:
        basis = "unusable"
    if refs:
        freshness = min((_ref_freshness(ref, reviewed, max_age_hours) for ref in refs), key=_FRESHNESS_RANK.__getitem__)
    else:
        freshness = "freshness_unknown"
        basis = "unusable"
    return {"basis": basis, "freshness": freshness, "states": states}


def _event_comparison(order_id: str, projected: Sequence[Event], repository: EventRepository | None) -> dict[str, Any]:
    if repository is None:
        return {"consulted": False, "read_count": 0, "appended": False, "comparison": "not_consulted", "stored_count": 0, "projected_count": len(projected)}
    read_count = 0
    stored_count = 0
    matched = 0
    try:
        stream = repository.stream(aggregate_id=order_id, limit=MAX_READS)
        for _event in stream:
            stored_count += 1
            read_count += 1
            if stored_count >= MAX_READS:
                break
        seen_ids: set[str] = set()
        conflicts = 0
        for event in projected[:MAX_READS]:
            if event.event_id in seen_ids:
                continue
            seen_ids.add(event.event_id)
            stored = repository.get(event.event_id)
            read_count += 1
            if stored is None:
                continue
            matched += 1
            if not isinstance(stored, Event) or stored.replay_hash() != event.replay_hash():
                conflicts += 1
    except Exception:
        return {
            "consulted": True,
            "read_count": read_count,
            "appended": False,
            "comparison": "unreadable",
            "stored_count": stored_count,
            "projected_count": len(projected),
        }
    if conflicts:
        comparison = "conflict"
    elif matched and matched < len(seen_ids):
        comparison = "partial"
    elif matched:
        comparison = "matches_projection"
    else:
        comparison = "not_present"
    return {
        "consulted": True,
        "read_count": read_count,
        "appended": False,
        "comparison": comparison,
        "stored_count": stored_count,
        "projected_count": len(projected),
    }


def _shell(*, reviewed_at: str, order_id: str | None, scenario_id: str | None) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "read_only": True,
        "live_action_allowed": False,
        "financial_fact": False,
        "risk_score": None,
        "amounts_omitted": True,
        "reviewed_at": reviewed_at,
        "order_id": order_id,
        "scenario_id": scenario_id,
        "prohibited_actions": list(PROHIBITED_ACTIONS),
        "mutations": {
            "refunds": False,
            "customer_contacts": False,
            "supplier_orders": False,
            "event_appends": False,
            "order_writes": False,
        },
    }


def _finish(document: dict[str, Any]) -> dict[str, Any]:
    encoded = _canonical(document)
    if any(marker in encoded.lower() for marker in _FORBIDDEN_MARKERS) or _SECRET_SHAPED.search(encoded):
        raise ValueError("unsafe review input")
    if len(encoded.encode("utf-8")) > MAX_REPORT_BYTES:
        raise ValueError("exception review exceeds output bound")
    return document


def _canonical(document: Mapping[str, Any]) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _decide(
    *,
    reviewed_at: str,
    order_id: str | None,
    scenario_id: str | None,
    transition: Mapping[str, Any],
    evidence: Mapping[str, Any],
    lifecycle_status: str,
    reserve_classifications: Sequence[str],
    tracking_unavailable: bool,
    events: Mapping[str, Any],
    path_only: bool,
) -> dict[str, Any]:
    current = transition.get("current_state")
    reasons: list[str] = list(transition.get("reasons") or [])
    notes: list[str] = []
    delayed = current == "delayed"
    failed = current == "failed_delivery"
    refund_visible = current in _REFUND_VISIBLE
    if delayed:
        reasons.append("delayed_delivery")
    if failed:
        reasons.append("failed_delivery")
    if refund_visible:
        reasons.append("refund_or_chargeback_visible")
    if lifecycle_status == "blocked":
        reasons.append("lifecycle_blocked")
    elif lifecycle_status == "hold":
        reasons.append("lifecycle_hold")
    if tracking_unavailable:
        reasons.append("tracking_unavailable")
    comparison = events.get("comparison")
    if comparison in {"conflict", "partial", "unreadable"}:
        reasons.append("event_store_" + str(comparison))
    freshness = evidence.get("freshness")
    basis = evidence.get("basis")
    if freshness in {"stale_for_review", "expired", "freshness_unknown", "freshness_inconsistent"}:
        reasons.append("evidence_" + str(freshness))
    elif basis == "unusable":
        reasons.append("evidence_unusable")
    elif basis == "not_evaluated":
        reasons.append("evidence_not_evaluated")
    elif basis in {"simulated", "mixed"}:
        notes.append("evidence_not_observed")
    if path_only:
        notes.append("full_dry_run_not_requested")
    attention_reasons = sorted(set(reasons))
    if not transition.get("valid"):
        step = "stop_and_review_recorded_path_do_not_advance"
        attention_required = True
    elif comparison in {"conflict", "partial", "unreadable"}:
        step = "compare_projection_to_stored_event_without_rewrite"
        attention_required = True
    elif failed:
        step = "read_failed_delivery_record_only"
        attention_required = True
    elif delayed:
        step = "read_delay_evidence_only"
        attention_required = True
    elif refund_visible:
        step = "read_refund_or_chargeback_state_do_not_initiate"
        attention_required = True
    elif lifecycle_status in {"blocked", "hold"} or tracking_unavailable:
        step = "resolve_recorded_blocker_without_external_action"
        attention_required = True
    elif freshness in {"stale_for_review", "expired", "freshness_unknown", "freshness_inconsistent"} or basis in {"unusable", "not_evaluated"}:
        step = "collect_sanitized_evidence_before_any_decision"
        attention_required = True
    elif basis in {"simulated", "mixed"} and lifecycle_status == "simulated" and not tracking_unavailable:
        step = "treat_as_fixture_not_observed"
        attention_required = False
    elif basis in {"simulated", "mixed"}:
        step = "treat_as_fixture_not_observed"
        attention_required = True
    else:
        step = "no_human_exception_review_required"
        attention_required = False
    document = _shell(reviewed_at=reviewed_at, order_id=order_id, scenario_id=scenario_id)
    document.update({
        "attention_required": attention_required,
        "attention_reasons": attention_reasons if attention_required else [],
        "notes": sorted(set(notes)),
        "transition_review": {
            "valid": bool(transition.get("valid")),
            "current_state": current,
            "steps": list(transition.get("steps") or []),
            "invalid_edges": list(transition.get("invalid_edges") or []),
            "reasons": list(transition.get("reasons") or []),
            "lifecycle_allowed_next": list(transition.get("lifecycle_allowed_next") or []),
            "lifecycle_allowed_next_are_not_actions": True,
        },
        "evidence": dict(evidence),
        "delivery_risk": {"delayed": delayed, "failed_delivery": failed},
        "lifecycle_status": lifecycle_status,
        "reserve_classifications": list(reserve_classifications),
        "event_store": dict(events),
        "next_safe_review_step": step,
    })
    return _finish(document)


def review_proposed_path(
    state_path: Sequence[str],
    *,
    order_id: str,
    reviewed_at: str,
) -> dict[str, Any]:
    """Explain a path that may be illegal. Does not run economics or append events."""
    reviewed = _require_reviewed_at(reviewed_at)
    safe_order = _reject_unsafe(order_id, "order_id")
    if not isinstance(state_path, (tuple, list)):
        raise ValueError("invalid state_path")
    for state in state_path[: MAX_STATE_COUNT + 1]:
        if not isinstance(state, str):
            continue
        if any(marker in state.lower() for marker in _FORBIDDEN_MARKERS) or _SECRET_SHAPED.search(state):
            raise ValueError("unsafe review input")
    transition = explain_state_path(state_path)
    evidence = _evidence_summary((), reviewed, DEFAULT_EVIDENCE_MAX_AGE_HOURS, evaluated=False)
    events = _event_comparison(safe_order, (), None)
    return _decide(
        reviewed_at=reviewed_at,
        order_id=safe_order,
        scenario_id=None,
        transition=transition,
        evidence=evidence,
        lifecycle_status="not_run",
        reserve_classifications=(),
        tracking_unavailable=False,
        events=events,
        path_only=True,
    )


def review_scenario(
    scenario: FulfillmentRiskScenario,
    *,
    reviewed_at: str,
    adapter: FulfillmentPortBundle | None = None,
    repository: EventRepository | None = None,
    max_evidence_age_hours: int = DEFAULT_EVIDENCE_MAX_AGE_HOURS,
    occurred_at: float = 0.0,
) -> dict[str, Any]:
    """Review one already-built scenario through the canonical dry-run. Never appends."""
    if not isinstance(scenario, FulfillmentRiskScenario):
        raise ValueError("invalid scenario")
    reviewed = _require_reviewed_at(reviewed_at)
    max_age = _bound_age(max_evidence_age_hours)
    report = run_fulfillment_risk_dry_run(scenario, adapter=adapter, occurred_at=occurred_at)
    transition = explain_state_path(scenario.state_path)
    evidence = _evidence_summary(report.evidence_refs, reviewed, max_age, evaluated=True)
    tracking_unavailable = any(
        item.capability == "tracking" and item.status != "simulated" for item in report.port_observations
    )
    events = _event_comparison(scenario.order_id, report.events, repository)
    return _decide(
        reviewed_at=reviewed_at,
        order_id=scenario.order_id,
        scenario_id=scenario.scenario_id,
        transition=transition,
        evidence=evidence,
        lifecycle_status=report.status,
        reserve_classifications=report.reserve_classifications,
        tracking_unavailable=tracking_unavailable,
        events=events,
        path_only=False,
    )


def build_failed_delivery_fixture() -> tuple[FulfillmentRiskScenario, FixtureFulfillmentAdapter]:
    """Named scenarios omit failed delivery. This fixture stays on the canonical edges."""
    base = build_named_scenario("shipment_delayed")
    scenario = FulfillmentRiskScenario(
        "failed_delivery_review",
        "order-failed-delivery",
        base.candidate_id,
        base.workspace_id,
        base.lane,
        base.price,
        base.product_cost,
        base.assumptions,
        base.responsibilities,
        (*base.state_path, "failed_delivery"),
        base.supplier_offer,
        base.catalog_item_id,
        base.flags,
        base.evidence_refs,
        base.evidence_state,
    )
    return scenario, FixtureFulfillmentAdapter.complete()


def review_named_fixture(
    name: str,
    *,
    reviewed_at: str,
    repository: EventRepository | None = None,
    max_evidence_age_hours: int = DEFAULT_EVIDENCE_MAX_AGE_HOURS,
    occurred_at: float = 0.0,
) -> dict[str, Any]:
    if name not in SCENARIO_NAMES:
        raise ValueError("unknown scenario")
    return review_scenario(
        build_named_scenario(name),
        reviewed_at=reviewed_at,
        adapter=build_named_adapter(name),
        repository=repository,
        max_evidence_age_hours=max_evidence_age_hours,
        occurred_at=occurred_at,
    )


def review_fixture_queue(
    *,
    reviewed_at: str,
    repository: EventRepository | None = None,
    max_evidence_age_hours: int = DEFAULT_EVIDENCE_MAX_AGE_HOURS,
    occurred_at: float = 0.0,
) -> dict[str, Any]:
    """Review the bounded named fixtures. Does not contact anyone or write events."""
    _require_reviewed_at(reviewed_at)
    if len(SCENARIO_NAMES) > MAX_QUEUE:
        raise ValueError("fixture queue exceeds bound")
    decisions = [
        review_named_fixture(
            name,
            reviewed_at=reviewed_at,
            repository=repository,
            max_evidence_age_hours=max_evidence_age_hours,
            occurred_at=occurred_at,
        )
        for name in SCENARIO_NAMES
    ]
    decisions.sort(key=lambda item: (not item["attention_required"], item["order_id"] or "", item["scenario_id"] or ""))
    document = {
        "schema": SCHEMA,
        "mode": "queue",
        "read_only": True,
        "live_action_allowed": False,
        "financial_fact": False,
        "risk_score": None,
        "amounts_omitted": True,
        "reviewed_at": reviewed_at,
        "attention_count": sum(1 for item in decisions if item["attention_required"]),
        "decisions": decisions,
        "prohibited_actions": list(PROHIBITED_ACTIONS),
        "mutations": {
            "refunds": False,
            "customer_contacts": False,
            "supplier_orders": False,
            "event_appends": False,
            "order_writes": False,
        },
    }
    return _finish(document)


def render_markdown(document: Mapping[str, Any], *, exceptions_only: bool = False) -> str:
    lines = [
        "# Fulfillment exception review",
        f"- Schema: `{document.get('schema')}`",
        "- Live action allowed: `false`",
        "- Refunds, customer contact, supplier orders, and event writes: not performed",
        "- Money amounts and risk scores: omitted",
    ]
    decisions = document.get("decisions")
    rows = decisions if isinstance(decisions, list) else [document]
    shown = 0
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        if exceptions_only and not item.get("attention_required"):
            continue
        shown += 1
        if shown > MAX_QUEUE:
            break
        lines.extend((
            f"- Order: `{item.get('order_id')}`",
            f"- Scenario: `{item.get('scenario_id')}`",
            f"- Attention: `{item.get('attention_required')}`",
            f"- State: `{item.get('transition_review', {}).get('current_state')}`",
            f"- Evidence: `{item.get('evidence', {}).get('basis')}` / `{item.get('evidence', {}).get('freshness')}`",
            f"- Next safe step: `{item.get('next_safe_review_step')}`",
        ))
    if shown == 0:
        lines.append("- No exception rows in this view")
    return "\n".join(lines)
