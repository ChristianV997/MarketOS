"""Draft-only creative experiment brief from synthesis and attention evidence.

Planning output only. Reuses Launch Draft Pack creative rows when a row's
message is already present in observed attention evidence. Does not score,
spend, target, publish, export a client packet, or start a campaign.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from evaluation.commerce.consumer_attention import normalize_geography, normalize_language
from evaluation.commerce.launch_draft_pack import build_launch_draft_pack

SCHEMA = "MarketOS.CreativeExperimentBrief.v1"
REF_SCHEMA = "MarketOS.CreativeEvidenceRef.v1"
LINEAGE_SCHEMA = "MarketOS.CreativeEvidenceLineage.v1"
_EVIDENCE_SOURCE = "consumer_attention.candidates.evidence"
_LIMIT = 180
_REF_LIMIT = 80
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SECRET_VALUE = re.compile(r"(?:api[_-]?key|access[_-]?token|secret[_-]?key|password)\s*[:=]\s*\S{6,}", re.I)
_PERSONAL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|\b\d{3}-\d{3}-\d{4}\b")
_OBSERVATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_SNAPSHOT_ID = re.compile(r"^snapshot:[a-f0-9]{32}$")
_SECRET_KEYS = frozenset({"cj_api_key", "authorization", "access_token", "secret_key", "password", "api_key"})
_UNSAFE_KEYS = _SECRET_KEYS | frozenset({"email", "phone", "raw_payload", "ssn", "customer_email"})
_THRESHOLD_FIELDS = (
    ("break_even_cpa", "cpa"),
    ("kill_if_cpa_above", "cpa"),
    ("scale_if_cpa_below", "scale"),
    ("kill_if_ctr_below", "ctr"),
    ("max_test_budget_recommendation", "budget"),
    ("scale_if_margin_above", "scale"),
)
_QUOTE_FIELDS = ("pain_point", "hook", "objection", "claim", "desired_outcome", "angle")
_AUTHORITY_FALSE = (
    "spend_authorized",
    "targeting_activated",
    "published",
    "ads_launched",
    "account_access",
    "customer_messages_sent",
    "orders_created",
    "payments_created",
    "launch_authorized",
    "financial_fact",
    "client_export",
    "provider_call",
    "campaign_published",
    "spend_executed",
)


def _secret_key(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    lowered = value.strip().lower().replace("-", "_")
    return lowered in _UNSAFE_KEYS or lowered.endswith(("_access_token", "_api_key", "_secret", "_password"))


def _require_safe(*values: Any) -> None:
    for value in values:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if _secret_key(key):
                    raise ValueError("unsafe creative brief input")
                _require_safe(item)
            continue
        if isinstance(value, (list, tuple)):
            for item in value:
                _require_safe(item)
            continue
        if isinstance(value, str) and (
            _CONTROL.search(value) or _SECRET_VALUE.search(value) or _PERSONAL.search(value)
        ):
            raise ValueError("unsafe creative brief input")


def _clip(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:_LIMIT]


def _same(left: str | None, right: str | None) -> bool:
    return bool(left and right and left.casefold() == right.casefold())


def _norm_geo(value: Any) -> str | None:
    try:
        return normalize_geography(value)
    except ValueError as exc:
        raise ValueError("unsafe creative brief input") from exc


def _norm_lang(value: Any) -> str | None:
    try:
        return normalize_language(value)
    except ValueError as exc:
        raise ValueError("unsafe creative brief input") from exc


def _authority() -> dict[str, bool]:
    authority = {
        "read_only": True,
        "draft_only": True,
        "planning_only": True,
    }
    authority.update({key: False for key in _AUTHORITY_FALSE})
    if authority["read_only"] is not True or any(authority[key] for key in _AUTHORITY_FALSE):
        raise ValueError("creative experiment briefs are draft-only")
    return authority


def _candidate_id(synthesis: Mapping[str, Any]) -> str:
    value = synthesis.get("top_candidate_id")
    if not isinstance(value, str):
        return ""
    return value.strip()


def _attention_candidate(report: Mapping[str, Any] | None, candidate_id: str) -> Mapping[str, Any] | None:
    if not isinstance(report, Mapping) or not candidate_id:
        return None
    rows = report.get("candidates")
    if not isinstance(rows, list):
        return None
    wanted = candidate_id.casefold()
    for row in rows:
        if isinstance(row, Mapping) and str(row.get("candidate_id") or "").strip().casefold() == wanted:
            return row
    return None


def _records(candidate: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if candidate is None:
        return []
    evidence = candidate.get("evidence")
    if not isinstance(evidence, list):
        return []
    return [row for row in evidence if isinstance(row, Mapping)]


_FRESHNESS_STATES = frozenset({"fresh", "stale", "future_dated", "unavailable"})


def _freshness_block(candidate: Mapping[str, Any] | None) -> str | None:
    """Return a blocker when the report's freshness set is not exclusively fresh.

    ``freshness_statuses`` is the unique set already stored on the attention
    candidate. It is not a per-record index, so a mixed or non-fresh set
    cannot be attributed to one evidence row. Those rows stay unlinked.
    A missing key is not rewritten into a freshness label.
    """
    if candidate is None or "freshness_statuses" not in candidate:
        return None
    raw = candidate.get("freshness_statuses")
    if not isinstance(raw, list) or not raw:
        return "attention_not_fresh"
    states: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            return "attention_not_fresh"
        state = item.strip().lower()
        if state not in _FRESHNESS_STATES:
            return "attention_not_fresh"
        states.append(state)
    if set(states) == {"fresh"}:
        return None
    if "stale" in states:
        return "stale_attention_evidence"
    return "attention_not_fresh"


def _market_reasons(
    records: Sequence[Mapping[str, Any]], geography: str, language: str
) -> tuple[list[str], list[str], list[str]]:
    geos = [geo for geo in (_norm_geo(row.get("geography")) for row in records) if geo]
    langs = [lang for lang in (_norm_lang(row.get("language")) for row in records) if lang]
    reasons: list[str] = []
    if not geos or not langs:
        reasons.append("attention_market_unobserved")
    if geos and not any(_same(item, geography) for item in geos):
        reasons.append("region_mismatch")
    if langs and not any(_same(item, language) for item in langs):
        reasons.append("language_mismatch")
    return reasons, list(dict.fromkeys(geos)), list(dict.fromkeys(langs))


def _matches(record: Mapping[str, Any], geography: str, language: str) -> bool:
    mode = str(record.get("evidence_mode") or "").strip().lower()
    return (
        mode == "observed"
        and _same(_norm_geo(record.get("geography")), geography)
        and _same(_norm_lang(record.get("language")), language)
    )


def _bounded(value: Any, limit: int = _REF_LIMIT) -> str | None:
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", value).strip()
    if not text or len(text) > limit or _CONTROL.search(text):
        return None
    return text


def _instant(value: Any) -> str | None:
    if not isinstance(value, str) or not _INSTANT.fullmatch(value.strip()):
        return None
    return value.strip()


def _supplied_observation_id(record: Mapping[str, Any]) -> str | None:
    """Return an id only when the record already has one. Never derive one."""
    if "observation_id" not in record:
        return None
    value = record.get("observation_id")
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not _OBSERVATION_ID.fullmatch(value.strip()):
        raise ValueError("unsafe creative brief input")
    return value.strip()


def _handoff_index(handoff: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    if handoff is None:
        return {}
    if not isinstance(handoff, Mapping):
        raise ValueError("unsafe creative brief input")
    raw = handoff.get("by_observation_id")
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError("unsafe creative brief input")
    index: dict[str, Mapping[str, Any]] = {}
    for key, item in raw.items():
        if not isinstance(key, str) or not _OBSERVATION_ID.fullmatch(key.strip()) or not isinstance(item, Mapping):
            raise ValueError("unsafe creative brief input")
        index[key.strip()] = item
    return index


def _identity(record: Mapping[str, Any], handoff: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Join only a supplied observation id with match_state exact_match."""
    base: dict[str, Any] = {
        "linkage": "source_local_unlinked",
        "candidate_id_is_cross_source_identity": False,
    }
    observation_id = _supplied_observation_id(record)
    if observation_id is None:
        return base
    base["observation_id"] = observation_id
    entry = handoff.get(observation_id)
    if not isinstance(entry, Mapping) or entry.get("match_state") != "exact_match":
        return base
    candidate_key = entry.get("candidate_key")
    if not isinstance(candidate_key, str) or not _OBSERVATION_ID.fullmatch(candidate_key.strip()):
        return base
    return {
        "linkage": "exact_match",
        "observation_id": observation_id,
        "candidate_key": candidate_key.strip(),
        "match_state": "exact_match",
        "candidate_id_is_cross_source_identity": False,
    }


def _snapshot(
    candidate_id: str,
    records: Sequence[Mapping[str, Any]],
    attention_row: Mapping[str, Any] | None,
    conflict_keys: Sequence[str],
) -> tuple[str, str]:
    freshness = None
    if attention_row is not None and "freshness_statuses" in attention_row:
        raw = attention_row.get("freshness_statuses")
        freshness = list(raw) if isinstance(raw, list) else None
    rows = []
    for index, record in enumerate(records):
        rows.append(
            {
                "index": index,
                "evidence_mode": _bounded(str(record.get("evidence_mode") or ""), 40),
                "geography": _bounded(record.get("geography")),
                "language": _bounded(record.get("language")),
                "observed_at": _instant(record.get("observed_at")),
                "source_reference": _bounded(record.get("source")),
                "fields": {name: _clip(record.get(name)) for name in _QUOTE_FIELDS},
            }
        )
    payload = {
        "source": _EVIDENCE_SOURCE,
        "report_local_candidate_id": candidate_id,
        "conflicting_observation_keys": list(conflict_keys),
        "freshness_statuses": freshness,
        "rows": rows,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()
    return digest, f"snapshot:{digest[:32]}"


def _supplied_snapshot_id(report: Mapping[str, Any] | None) -> str | None:
    if not isinstance(report, Mapping) or "report_snapshot_id" not in report:
        return None
    value = report.get("report_snapshot_id")
    if not isinstance(value, str) or not _SNAPSHOT_ID.fullmatch(value.strip()):
        raise ValueError("unsafe creative brief input")
    return value.strip()


def _insight_observation_ids(insights: Mapping[str, Any] | None) -> list[str]:
    if insights is None:
        return []
    found: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            if "observation_id" in value:
                observation_id = _supplied_observation_id(value)
                if observation_id:
                    found.append(observation_id)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(insights)
    return list(dict.fromkeys(found))


def _ref(
    ctx: Mapping[str, Any], candidate_id: str, index: int, field: str, record: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "schema": REF_SCHEMA,
        "source": _EVIDENCE_SOURCE,
        "evidence_mode": "observed",
        "evidence_class": "observed",
        "report_snapshot_id": ctx["report_snapshot_id"],
        "snapshot_digest": ctx["snapshot_digest"],
        "snapshot_digest_authenticates_source": False,
        "record_index": index,
        "observed_at": _instant(record.get("observed_at")),
        "geography": _bounded(record.get("geography")),
        "language": _bounded(record.get("language")),
        "field": field,
        "freshness": ctx["freshness"],
        "conflict_state": "none",
        "source_reference": _bounded(record.get("source")),
        "candidate_id": candidate_id,
        "candidate_id_is_cross_source_identity": False,
        "identity": _identity(record, ctx["handoff"]),
    }


def _problems(
    ctx: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    candidate_id: str,
    geography: str,
    language: str,
) -> list[dict[str, Any]]:
    problems: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        if not _matches(record, geography, language):
            continue
        statement = _clip(record.get("pain_point"))
        key = statement.casefold()
        if not statement or key in seen:
            continue
        seen.add(key)
        problems.append(
            {
                "statement": statement,
                "evidence_refs": [_ref(ctx, candidate_id, index, "pain_point", record)],
                "product_fact": False,
            }
        )
        if len(problems) == 3:
            break
    return problems


def _hypotheses(
    ctx: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    candidate_id: str,
    geography: str,
    language: str,
    problems: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    hypotheses: list[dict[str, Any]] = []
    seen: set[str] = set()
    primary = problems[0]["evidence_refs"][0]["record_index"] if problems else None
    for index, record in enumerate(records):
        if not _matches(record, geography, language):
            continue
        message = _clip(record.get("hook"))
        key = message.casefold()
        if not message or key in seen:
            continue
        seen.add(key)
        refs = [_ref(ctx, candidate_id, index, "hook", record)]
        if _clip(record.get("pain_point")):
            refs.append(_ref(ctx, candidate_id, index, "pain_point", record))
        elif primary is not None:
            refs.append(_ref(ctx, candidate_id, primary, "pain_point", records[primary]))
        angle = _clip(record.get("angle")) or "unspecified"
        if angle != "unspecified":
            refs.append(_ref(ctx, candidate_id, index, "angle", record))
        objection = _clip(record.get("objection"))
        item: dict[str, Any] = {
            "id": f"h{len(hypotheses) + 1}",
            "message": message,
            "angle": angle,
            "evidence_refs": refs,
            "status": "testable_draft",
            "product_fact": False,
        }
        if objection:
            item["objection"] = objection
            item["evidence_refs"] = [*refs, _ref(ctx, candidate_id, index, "objection", record)]
        hypotheses.append(item)
        if len(hypotheses) == 3:
            break
    return hypotheses


def _unsupported(
    asserted_claims: Sequence[str], records: Sequence[Mapping[str, Any]], geography: str, language: str
) -> list[dict[str, str]]:
    rejected: list[dict[str, str]] = []
    seen: set[str] = set()
    for claim in asserted_claims:
        text = _clip(claim)
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        supported = False
        for record in records:
            if not _matches(record, geography, language):
                continue
            if any(_clip(record.get(field)).casefold() == key for field in _QUOTE_FIELDS):
                supported = True
                break
        if not supported:
            rejected.append({"text": text, "reason": "unsupported_claim"})
    return rejected


def _contains_rejected(value: str, rejected: Sequence[Mapping[str, str]]) -> bool:
    folded = value.casefold()
    return any(len(item["text"]) >= 4 and item["text"].casefold() in folded for item in rejected)


def _measurement(synthesis: Mapping[str, Any]) -> dict[str, Any]:
    raw = synthesis.get("decision_thresholds")
    thresholds = raw if isinstance(raw, Mapping) else {}
    rows: list[dict[str, Any]] = []
    for field, kind in _THRESHOLD_FIELDS:
        value = thresholds.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float, str)) or value == "":
            rows.append(
                {
                    "kind": kind,
                    "field": field,
                    "value": None,
                    "label": "assumption",
                    "status": "unevaluated",
                    "financial_fact": False,
                    "source": "opportunity_synthesis.decision_thresholds",
                }
            )
        else:
            rows.append(
                {
                    "kind": kind,
                    "field": field,
                    "value": value,
                    "label": "assumption",
                    "status": "copied_assumption",
                    "financial_fact": False,
                    "source": "opportunity_synthesis.decision_thresholds",
                    "copied_not_recomputed": True,
                }
            )
    rows.append(
        {
            "kind": "lift",
            "field": None,
            "value": None,
            "label": "assumption",
            "status": "unevaluated",
            "financial_fact": False,
            "source": "not_on_synthesis_contract",
            "note": "No lift figure is invented. The synthesis contract has no lift field.",
        }
    )
    labels = thresholds.get("assumptions")
    copied = (
        [_clip(item) for item in labels if isinstance(item, str) and _clip(item)] if isinstance(labels, list) else []
    )
    return {
        "proposed_metrics": ["message_comprehension", "ctr", "cpa", "lift"],
        "result_status": "not_measured",
        "thresholds": rows,
        "synthesis_assumption_labels": copied,
        "note": "CPA, CTR, budget, lift, and scale values are planning assumptions, not observed results and not spend authorization.",
    }


def _pack_link(synthesis: Mapping[str, Any], attention: Mapping[str, Any] | None, messages: set[str]) -> dict[str, Any]:
    pack = build_launch_draft_pack(
        synthesis=synthesis, consumer_attention=attention if isinstance(attention, Mapping) else None
    )
    rows = pack.creative_test_matrix.rows
    linked = 0
    for row in rows:
        hook = _clip(row.get("hook") if isinstance(row, Mapping) else "").casefold()
        if hook and hook in messages:
            linked += 1
    return {
        "reused": True,
        "builder": "evaluation.commerce.launch_draft_pack.build_launch_draft_pack",
        "launch_draft_status": pack.launch_draft_status,
        "matrix_row_count": len(rows),
        "matrix_rows_linked_to_observed_hooks": linked,
        "matrix_rows_not_used_as_facts": len(rows) - linked,
    }


_UPSTREAM_CONTRACT = {
    "name": "product-identity-synthesis-handoff-v1",
    "join": "by_observation_id[observation_id] where match_state is exact_match",
    "not_sufficient": ["candidate_id", "candidate_id_hint", "title", "geography", "insight_id", "record_index"],
    "insight_schema_gap": "AttentionInsight.to_dict does not publish observation_id",
}


def _evidence_lineage(
    *,
    ctx: Mapping[str, Any],
    attention_row: Mapping[str, Any] | None,
    attention: Mapping[str, Any] | None,
    conflict_keys: Sequence[str],
    problems: Sequence[Mapping[str, Any]],
    hypotheses: Sequence[Mapping[str, Any]],
    handoff: Mapping[str, Mapping[str, Any]],
    consumer_insights: Mapping[str, Any] | None,
    supplied_snapshot: str | None,
) -> dict[str, Any]:
    linked: list[dict[str, Any]] = []
    for item in (*problems, *hypotheses):
        for ref in item.get("evidence_refs") or []:
            linked.append(
                {"record_index": ref["record_index"], "field": ref["field"], "linkage": ref["identity"]["linkage"]}
            )
    linkages = {item["linkage"] for item in linked}
    if linkages == {"exact_match"}:
        linkage = "exact_match"
    elif "exact_match" in linkages:
        linkage = "partial_exact_match"
    else:
        linkage = "source_local_unlinked"
    freshness = None
    if attention_row is not None and "freshness_statuses" in attention_row:
        raw = attention_row.get("freshness_statuses")
        freshness = list(raw) if isinstance(raw, list) else None
    lineage: dict[str, Any] = {
        "schema": LINEAGE_SCHEMA,
        "source": _EVIDENCE_SOURCE,
        "report_snapshot_id": ctx["report_snapshot_id"],
        "snapshot_digest": ctx["snapshot_digest"],
        "snapshot_digest_authenticates_source": False,
        "supplied_report_snapshot_id": supplied_snapshot,
        "freshness_statuses": freshness,
        "conflict_state": "conflicting" if conflict_keys else "none",
        "conflicting_observation_keys": list(conflict_keys),
        "linked_fields": linked,
        "identity": {
            "linkage": linkage,
            "exact_match_count": sum(item["linkage"] == "exact_match" for item in linked),
            "candidate_id_is_cross_source_identity": False,
            "required_upstream_contract": None if linkage == "exact_match" else dict(_UPSTREAM_CONTRACT),
        },
    }
    if consumer_insights is not None:
        insight_ids = _insight_observation_ids(consumer_insights)
        lineage["insight_boundary"] = {
            "inspected": True,
            "observation_id_present": bool(insight_ids),
            "exact_match_count": sum(
                isinstance(handoff.get(item), Mapping) and handoff[item].get("match_state") == "exact_match"
                for item in insight_ids
            ),
            "statements_used_as_hypotheses": False,
            "linkage": "source_local_unlinked" if not insight_ids else "unlinked_without_attention_observation_id",
        }
    if attention is None:
        lineage["attention_report_present"] = False
    return lineage


def build_creative_experiment_brief(
    *,
    synthesis: Mapping[str, Any],
    consumer_attention: Mapping[str, Any] | None,
    target_geography: str,
    target_language: str,
    asserted_claims: Sequence[str] = (),
    identity_handoff: Mapping[str, Any] | None = None,
    consumer_insights: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one planning brief. Insufficient evidence is a successful safe result."""
    if not isinstance(synthesis, Mapping):
        raise ValueError("unsafe creative brief input")
    _require_safe(
        synthesis,
        consumer_attention,
        target_geography,
        target_language,
        list(asserted_claims),
        identity_handoff,
        consumer_insights,
    )
    geography = _norm_geo(target_geography)
    language = _norm_lang(target_language)
    reasons: list[str] = []
    if not geography or not language:
        reasons.append("market_context_required")
        geography = geography or ""
        language = language or ""
    candidate_id = _candidate_id(synthesis)
    if not candidate_id:
        reasons.append("missing_candidate")
    attention = consumer_attention if isinstance(consumer_attention, Mapping) else None
    attention_row = _attention_candidate(attention, candidate_id)
    records = _records(attention_row)
    conflict_keys: list[str] = []
    if attention_row is None:
        reasons.append("missing_attention_evidence")
    else:
        conflicts = attention_row.get("conflicting_observation_keys") or []
        if not isinstance(conflicts, list):
            conflicts = []
        conflict_keys = [_clip(item) for item in conflicts if _clip(item)]
        if conflict_keys:
            reasons.append("contradictory_attention_evidence")
        if records:
            market_reasons, observed_geos, observed_langs = _market_reasons(records, geography, language)
            reasons.extend(market_reasons)
        else:
            observed_geos, observed_langs = [], []
            if "missing_attention_evidence" not in reasons:
                reasons.append("missing_attention_evidence")
        freshness_reason = _freshness_block(attention_row)
        if freshness_reason:
            reasons.append(freshness_reason)
    if attention_row is None:
        observed_geos, observed_langs = [], []
    blocked = (
        "contradictory_attention_evidence" in reasons
        or "missing_attention_evidence" in reasons
        or "market_context_required" in reasons
        or "stale_attention_evidence" in reasons
        or "attention_not_fresh" in reasons
    )
    market_blocked = any(
        item in reasons for item in ("region_mismatch", "language_mismatch", "attention_market_unobserved")
    )
    digest, snapshot_id = _snapshot(candidate_id, records, attention_row, conflict_keys)
    supplied_snapshot = _supplied_snapshot_id(attention)
    handoff = _handoff_index(identity_handoff)
    freshness_label = (
        "fresh"
        if attention_row is not None
        and "freshness_statuses" in attention_row
        and _freshness_block(attention_row) is None
        else "not_supplied"
    )
    ctx = {
        "report_snapshot_id": snapshot_id,
        "snapshot_digest": digest,
        "freshness": freshness_label,
        "handoff": handoff,
    }
    problems = (
        []
        if blocked or market_blocked or not geography or not language
        else _problems(ctx, records, candidate_id, geography, language)
    )
    hypotheses = [] if not problems else _hypotheses(ctx, records, candidate_id, geography, language, problems)
    if not blocked and not market_blocked and attention_row is not None and records and not problems:
        reasons.append("missing_observed_attention")
    if problems and not hypotheses:
        reasons.append("no_testable_message")
    linkable = [] if blocked else records
    rejected = (
        _unsupported(asserted_claims, linkable, geography, language)
        if geography and language
        else [{"text": _clip(item), "reason": "unsupported_claim"} for item in asserted_claims if _clip(item)]
    )
    if rejected:
        problems = [item for item in problems if not _contains_rejected(item["statement"], rejected)]
        hypotheses = [
            item
            for item in hypotheses
            if not _contains_rejected(item["message"], rejected)
            and not _contains_rejected(str(item.get("objection") or ""), rejected)
        ]
        if not problems and "missing_observed_attention" not in reasons and "missing_attention_evidence" not in reasons:
            reasons.append("unsupported_claims_only")
    title = _clip(synthesis.get("top_candidate_title")) if isinstance(synthesis.get("top_candidate_title"), str) else ""
    if title and _contains_rejected(title, rejected):
        title = ""
    outcome = (
        "draft_brief"
        if problems
        and hypotheses
        and not any(
            item in reasons
            for item in (
                "missing_candidate",
                "missing_attention_evidence",
                "contradictory_attention_evidence",
                "region_mismatch",
                "language_mismatch",
                "attention_market_unobserved",
                "market_context_required",
                "stale_attention_evidence",
                "attention_not_fresh",
                "missing_observed_attention",
                "no_testable_message",
                "unsupported_claims_only",
            )
        )
        else "insufficient_evidence"
    )
    if outcome != "draft_brief":
        problems = []
        hypotheses = []
    messages = {item["message"].casefold() for item in hypotheses}
    pack = (
        _pack_link(synthesis, consumer_attention if isinstance(consumer_attention, Mapping) else None, messages)
        if candidate_id
        else {
            "reused": False,
            "builder": "evaluation.commerce.launch_draft_pack.build_launch_draft_pack",
            "reason": "missing_candidate",
        }
    )
    lineage = _evidence_lineage(
        ctx=ctx,
        attention_row=attention_row,
        attention=attention,
        conflict_keys=conflict_keys,
        problems=problems,
        hypotheses=hypotheses,
        handoff=handoff,
        consumer_insights=consumer_insights,
        supplied_snapshot=supplied_snapshot,
    )
    document = {
        "schema": SCHEMA,
        "outcome": outcome,
        "candidate_id": candidate_id or None,
        "candidate_title": title or None,
        "customer_problem": problems[0] if problems else None,
        "alternate_problems": problems[1:],
        "hypotheses": hypotheses,
        "evidence_lineage": lineage,
        "audience_market": {
            "target_geography": geography or None,
            "target_language": language or None,
            "observed_geographies": observed_geos,
            "observed_languages": observed_langs,
            "targeting_activated": False,
            "note": "Geography and language labels are copied from attention evidence. This brief does not activate targeting.",
        },
        "measurement": _measurement(synthesis),
        "claim_guardrails": {
            "product_claims_allowed": False,
            "unsupported_claims": rejected,
            "observed_language_is_not_a_product_fact": True,
            "do_not_treat_as_fact": ["cpa", "ctr", "budget", "lift", "scale", "profit"],
        },
        "insufficient_evidence_reasons": [] if outcome == "draft_brief" else list(dict.fromkeys(reasons)),
        "conflicting_observation_keys": conflict_keys,
        "launch_draft_pack": pack,
        "authority": _authority(),
        "financial_fact": False,
        "next_safe_step": "human_review_before_any_test_design"
        if outcome == "draft_brief"
        else "collect_sanitized_attention_evidence_before_a_brief",
    }
    _require_safe(document)
    return document
