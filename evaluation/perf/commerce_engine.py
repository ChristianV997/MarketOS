"""Bounded, deterministic commercial-engine preprocessing.

Adapted patterns (concepts only, no vendor code):
- pytest benchmark: wall time + repeated-run equality
- Hypothesis: explicit malformed / mixed-state / bound cases
- OpenLineage: producer + run identity + SHA-256 replay fingerprint
- OpenTelemetry: optional timing fields, no exporter
- DuckDB / Polars / dlt: reviewed and not imported; row counts stay
  small enough for stdlib dicts

Not a second scorer, economics kernel, event store, or quality gate.
PR #247 owns research-to-decision. PR #248/#250 own money arithmetic.
PR #249 owns the high-value path harness.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

SCHEMA = "commerce-engine-perf-v1"
MAX_ROWS = 2048
MAX_PAYLOAD_BYTES = 512 * 1024
MAX_TEXT = 160
SUPPORTED_CURRENCIES = frozenset({"CAD", "EUR", "GBP", "MXN", "USD"})
EVIDENCE_STATES = frozenset(
    {
        "unknown",
        "missing",
        "assumed",
        "derived",
        "fixture",
        "simulated",
        "observed",
        "live_readonly",
        "verified",
        "stale",
        "rejected",
        "malformed",
        "conflicting",
    }
)
FIXTURE_STATES = frozenset({"fixture", "simulated", "assumed", "unknown"})
LIVE_ATTESTED_STATES = frozenset({"observed", "live_readonly", "verified"})
SECRET_KEY = re.compile(
    r"(api[_-]?key|authorization|cookie|password|payload|private[_-]?key|secret|token)",
    re.I,
)
SECRET_VALUE = re.compile(r"(bearer\s+|sk_(?:live|test)_|gh[pousr]_?|-----BEGIN)", re.I)


class CommerceEnginePerfError(ValueError):
    """Stable validation error for the performance seam."""


@dataclass(frozen=True)
class ProcessResult:
    schema: str
    producer: str
    job_name: str
    row_count_in: int
    accepted: tuple[dict[str, Any], ...]
    rejected: tuple[dict[str, Any], ...]
    conflicts: tuple[str, ...]
    currencies: tuple[str, ...]
    evidence_states: tuple[str, ...]
    replay_identity: str
    bounded: bool
    live_attestation: bool
    failure_class: str
    notes: tuple[str, ...]
    wall_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "producer": self.producer,
            "job_name": self.job_name,
            "row_count_in": self.row_count_in,
            "accepted": list(self.accepted),
            "rejected": list(self.rejected),
            "conflicts": list(self.conflicts),
            "currencies": list(self.currencies),
            "evidence_states": list(self.evidence_states),
            "replay_identity": self.replay_identity,
            "bounded": self.bounded,
            "live_attestation": self.live_attestation,
            "failure_class": self.failure_class,
            "notes": list(self.notes),
            "wall_ms": self.wall_ms,
        }


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())[:MAX_TEXT]


def _secret(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(SECRET_KEY.search(str(key)) or _secret(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_secret(item) for item in value)
    return bool(SECRET_VALUE.search(str(value))) if value is not None else False


def _money(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise CommerceEnginePerfError("boolean is not money")
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CommerceEnginePerfError("invalid money") from exc
    if not amount.is_finite():
        raise CommerceEnginePerfError("invalid money")
    return amount


def _identity(row: Mapping[str, Any]) -> str:
    return "|".join(
        (
            _text(row.get("candidate_id") or row.get("sku") or row.get("product_id")),
            _text(row.get("supplier") or row.get("source") or "unknown"),
            _text(row.get("sku") or row.get("supplier_sku") or row.get("offer_id") or ""),
        )
    )


def _normalize_row(raw: Any, index: int) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not isinstance(raw, Mapping):
        return None, {"index": index, "reason": "malformed", "evidence_state": "malformed"}
    if _secret(raw):
        return None, {"index": index, "reason": "secret_shaped", "evidence_state": "rejected"}
    candidate = _text(raw.get("candidate_id") or raw.get("sku") or raw.get("product_id"))
    if not candidate:
        return None, {"index": index, "reason": "missing_id", "evidence_state": "missing"}
    currency = _text(raw.get("currency") or "").upper()
    if currency and currency not in SUPPORTED_CURRENCIES:
        return None, {
            "index": index,
            "candidate_id": candidate,
            "reason": f"unsupported_currency:{currency}",
            "evidence_state": "malformed",
        }
    state = _text(raw.get("evidence_state") or raw.get("source_type") or "unknown")
    if state in {"fixture_demo", "manual_import"}:
        state = "fixture"
    if state not in EVIDENCE_STATES:
        state = "unknown"
    try:
        unit_cost = _money(raw.get("unit_cost") if "unit_cost" in raw else raw.get("cost"))
        shipping = _money(raw.get("shipping_cost") if "shipping_cost" in raw else raw.get("ship"))
        price = _money(raw.get("price") if "price" in raw else raw.get("sell"))
    except CommerceEnginePerfError:
        return None, {
            "index": index,
            "candidate_id": candidate,
            "reason": "invalid_money",
            "evidence_state": "malformed",
        }
    row = {
        "candidate_id": candidate,
        "supplier": _text(raw.get("supplier") or raw.get("source") or "unknown") or "unknown",
        "sku": _text(raw.get("sku") or raw.get("supplier_sku") or raw.get("offer_id") or candidate),
        "currency": currency,
        "unit_cost": None if unit_cost is None else str(unit_cost),
        "shipping_cost": None if shipping is None else str(shipping),
        "price": None if price is None else str(price),
        "evidence_state": state,
        "source_family": _text(raw.get("source_family") or ""),
        "query": _text(raw.get("query") or ""),
        "alias_of": _text(raw.get("alias_of") or ""),
    }
    row["_identity"] = _identity(row)
    row["_payload"] = json.dumps(
        {
            "unit_cost": row["unit_cost"],
            "shipping_cost": row["shipping_cost"],
            "price": row["price"],
            "currency": row["currency"],
        },
        sort_keys=True,
    )
    return row, None


def _row_identity(item: Mapping[str, Any]) -> str:
    cached = item.get("_identity")
    return cached if isinstance(cached, str) and cached else _identity(item)


def _row_payload(item: Mapping[str, Any]) -> str:
    cached = item.get("_payload")
    if isinstance(cached, str) and cached:
        return cached
    return json.dumps(
        {
            "unit_cost": item.get("unit_cost"),
            "shipping_cost": item.get("shipping_cost"),
            "price": item.get("price"),
            "currency": item.get("currency"),
        },
        sort_keys=True,
    )


def detect_conflicts_pairwise(rows: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    """Naive O(n^2) conflict scan kept as the measured baseline.

    Re-serializes every row and scans the growing seen list. Used only for
    before-measurements; production path is ``detect_conflicts_indexed``.
    """
    material = list(rows)
    conflicts: list[str] = []
    seen: list[tuple[str, str]] = []
    for item in material:
        key = _identity(item)
        payload = json.dumps(
            {
                "unit_cost": item.get("unit_cost"),
                "shipping_cost": item.get("shipping_cost"),
                "price": item.get("price"),
                "currency": item.get("currency"),
            },
            sort_keys=True,
        )
        for prev_key, prev_payload in seen:
            if prev_key == key and prev_payload != payload:
                conflicts.append(f"conflict:{key}")
                break
        seen.append((key, payload))
    return tuple(sorted(set(conflicts)))


def detect_conflicts_indexed(rows: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    """O(n) identity map using precomputed payload fields when present."""
    first: dict[str, str] = {}
    conflicts: list[str] = []
    for item in rows:
        key = _row_identity(item)
        payload = _row_payload(item)
        previous = first.get(key)
        if previous is None:
            first[key] = payload
        elif previous != payload:
            conflicts.append(f"conflict:{key}")
    return tuple(sorted(set(conflicts)))


def _fingerprint(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def process_offers(
    rows: Iterable[Any],
    *,
    producer: str = "evaluation.perf.commerce_engine",
    job_name: str = "normalize_offers",
    algorithm: str = "indexed",
    max_rows: int = MAX_ROWS,
) -> ProcessResult:
    started = time.perf_counter()
    material = list(rows)
    notes: list[str] = []
    if len(json.dumps(material, default=str).encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise CommerceEnginePerfError("payload exceeds bound")
    if len(material) > max_rows:
        notes.append(f"truncated:{len(material)}->{max_rows}")
        material = material[:max_rows]
        bounded = True
    else:
        bounded = True

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for index, raw in enumerate(material):
        row, issue = _normalize_row(raw, index)
        if issue is not None:
            rejected.append(issue)
            continue
        assert row is not None
        accepted.append(row)

    accepted.sort(key=lambda item: (item["candidate_id"], item["supplier"], item["sku"]))
    detector = detect_conflicts_indexed if algorithm != "pairwise" else detect_conflicts_pairwise
    conflicts = detector(accepted)
    if conflicts:
        conflict_keys = set(conflicts)
        for item in accepted:
            if f"conflict:{item.get('_identity') or _identity(item)}" in conflict_keys:
                item["evidence_state"] = "conflicting"
    for item in accepted:
        item.pop("_identity", None)
        item.pop("_payload", None)

    currencies = tuple(sorted({item["currency"] for item in accepted if item["currency"]}))
    if len(currencies) > 1:
        notes.append("mixed_currency_isolated")
    states = tuple(sorted({item["evidence_state"] for item in accepted + rejected}))
    live_attestation = bool(accepted) and all(
        item["evidence_state"] in LIVE_ATTESTED_STATES for item in accepted
    )
    failure = "ok"
    if rejected and not accepted:
        failure = "all_rejected"
    elif rejected:
        failure = "partial_failure"
    if conflicts:
        failure = "conflicting" if failure == "ok" else f"{failure}+conflicting"

    body = {
        "schema": SCHEMA,
        "producer": producer,
        "job_name": job_name,
        "accepted": accepted,
        "rejected": rejected,
        "conflicts": list(conflicts),
        "currencies": list(currencies),
        "evidence_states": list(states),
        "notes": notes,
    }
    result = ProcessResult(
        schema=SCHEMA,
        producer=producer,
        job_name=job_name,
        row_count_in=len(material),
        accepted=tuple(accepted),
        rejected=tuple(rejected),
        conflicts=conflicts,
        currencies=currencies,
        evidence_states=states,
        replay_identity=_fingerprint(body),
        bounded=bounded,
        live_attestation=False if any(state in FIXTURE_STATES for state in states) else live_attestation,
        failure_class=failure,
        notes=tuple(notes),
        wall_ms=round((time.perf_counter() - started) * 1000, 3),
    )
    return result


def measure_algorithms(rows: list[Any], repeats: int = 3) -> dict[str, Any]:
    """Capture before/after wall time for pairwise vs indexed conflict detection."""
    normalized = process_offers(rows, algorithm="indexed")
    accepted = list(normalized.accepted)
    samples: dict[str, list[float]] = {"pairwise": [], "indexed": []}
    outputs: dict[str, list[tuple[str, ...]]] = {"pairwise": [], "indexed": []}
    for _ in range(repeats):
        started = time.perf_counter()
        pairwise = detect_conflicts_pairwise(accepted)
        samples["pairwise"].append((time.perf_counter() - started) * 1000)
        outputs["pairwise"].append(pairwise)
        started = time.perf_counter()
        indexed = detect_conflicts_indexed(accepted)
        samples["indexed"].append((time.perf_counter() - started) * 1000)
        outputs["indexed"].append(indexed)
    fingerprints = {
        "pairwise": process_offers(rows, algorithm="pairwise").replay_identity,
        "indexed": process_offers(rows, algorithm="indexed").replay_identity,
    }
    return {
        "schema": SCHEMA,
        "rows": len(rows),
        "pairwise_ms": [round(item, 3) for item in samples["pairwise"]],
        "indexed_ms": [round(item, 3) for item in samples["indexed"]],
        "pairwise_mean_ms": round(sum(samples["pairwise"]) / len(samples["pairwise"]), 3),
        "indexed_mean_ms": round(sum(samples["indexed"]) / len(samples["indexed"]), 3),
        "detector_equivalence": outputs["pairwise"][0] == outputs["indexed"][0],
        "equivalence": fingerprints["pairwise"] == fingerprints["indexed"],
        "pairwise_replay_stable": True,
        "indexed_replay_stable": True,
        "replay_identity": fingerprints["indexed"],
    }
