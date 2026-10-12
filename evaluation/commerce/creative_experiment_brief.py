"""Draft-only creative experiment brief from synthesis and attention evidence.

Planning output only. Reuses Launch Draft Pack creative rows when a row's
message is already present in observed attention evidence. Does not score,
spend, target, publish, export a client packet, or start a campaign.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from evaluation.commerce.consumer_attention import normalize_geography, normalize_language
from evaluation.commerce.launch_draft_pack import build_launch_draft_pack

SCHEMA = "MarketOS.CreativeExperimentBrief.v1"
_LIMIT = 180
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SECRET_VALUE = re.compile(r"(?:api[_-]?key|access[_-]?token|secret[_-]?key|password)\s*[:=]\s*\S{6,}", re.I)
_SECRET_KEYS = frozenset({"cj_api_key", "authorization", "access_token", "secret_key", "password", "api_key"})
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
    return lowered in _SECRET_KEYS or lowered.endswith(("_access_token", "_api_key", "_secret", "_password"))


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
        if isinstance(value, str) and (_CONTROL.search(value) or _SECRET_VALUE.search(value)):
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


def _ref(candidate_id: str, index: int, field: str) -> dict[str, Any]:
    return {
        "source": "consumer_attention.candidates.evidence",
        "candidate_id": candidate_id,
        "record_index": index,
        "field": field,
        "evidence_mode": "observed",
    }


def _problems(
    records: Sequence[Mapping[str, Any]], candidate_id: str, geography: str, language: str
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
            {"statement": statement, "evidence_refs": [_ref(candidate_id, index, "pain_point")], "product_fact": False}
        )
        if len(problems) == 3:
            break
    return problems


def _hypotheses(
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
        refs = [_ref(candidate_id, index, "hook")]
        if _clip(record.get("pain_point")):
            refs.append(_ref(candidate_id, index, "pain_point"))
        elif primary is not None:
            refs.append(_ref(candidate_id, primary, "pain_point"))
        angle = _clip(record.get("angle")) or "unspecified"
        if angle != "unspecified":
            refs.append(_ref(candidate_id, index, "angle"))
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
            item["evidence_refs"] = [*refs, _ref(candidate_id, index, "objection")]
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


def build_creative_experiment_brief(
    *,
    synthesis: Mapping[str, Any],
    consumer_attention: Mapping[str, Any] | None,
    target_geography: str,
    target_language: str,
    asserted_claims: Sequence[str] = (),
) -> dict[str, Any]:
    """Build one planning brief. Insufficient evidence is a successful safe result."""
    if not isinstance(synthesis, Mapping):
        raise ValueError("unsafe creative brief input")
    _require_safe(synthesis, consumer_attention, target_geography, target_language, list(asserted_claims))
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
    attention_row = _attention_candidate(
        consumer_attention if isinstance(consumer_attention, Mapping) else None, candidate_id
    )
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
    if attention_row is None:
        observed_geos, observed_langs = [], []
    blocked = (
        "contradictory_attention_evidence" in reasons
        or "missing_attention_evidence" in reasons
        or "market_context_required" in reasons
    )
    market_blocked = any(
        item in reasons for item in ("region_mismatch", "language_mismatch", "attention_market_unobserved")
    )
    problems = (
        []
        if blocked or market_blocked or not geography or not language
        else _problems(records, candidate_id, geography, language)
    )
    hypotheses = [] if not problems else _hypotheses(records, candidate_id, geography, language, problems)
    if not blocked and not market_blocked and attention_row is not None and records and not problems:
        reasons.append("missing_observed_attention")
    if problems and not hypotheses:
        reasons.append("no_testable_message")
    rejected = (
        _unsupported(asserted_claims, records, geography, language)
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
    document = {
        "schema": SCHEMA,
        "outcome": outcome,
        "candidate_id": candidate_id or None,
        "candidate_title": title or None,
        "customer_problem": problems[0] if problems else None,
        "alternate_problems": problems[1:],
        "hypotheses": hypotheses,
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
