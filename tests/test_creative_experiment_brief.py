from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from evaluation.commerce import creative_experiment_brief as brief

ROOT = Path(__file__).resolve().parents[1]
UNSUPPORTED = "clinically proven overnight wrinkle cure"


def _synthesis(**extra):
    document = {
        "top_candidate_id": "cand-1",
        "top_candidate_title": "Compact steamer",
        "overall_recommendation": "hold_for_manual_review",
        "evidence_mode": "fixture",
        "top_pain_points": ["A common task still takes more effort than customers want."],
        "top_hooks": ["See Compact steamer in use"],
        "decision_thresholds": {
            "break_even_cpa": 12.5,
            "kill_if_cpa_above": 18,
            "scale_if_cpa_below": 8,
            "kill_if_ctr_below": 0.008,
            "max_test_budget_recommendation": 150,
            "scale_if_margin_above": 0.35,
            "assumptions": [
                "ctr_and_add_to_cart_thresholds_are_planning_assumptions",
                "test_budget_is_a_rule_of_thumb_not_a_spend_authorization",
            ],
        },
    }
    document.update(extra)
    return document


def _record(**extra):
    document = {
        "candidate_id": "cand-1",
        "pain_point": "wrinkles before a meeting",
        "hook": "show the collar before the meeting",
        "objection": "thick fabric may not respond",
        "claim": "",
        "angle": "demo",
        "geography": "MX",
        "language": "es",
        "evidence_mode": "observed",
        "source": "manual-note",
    }
    document.update(extra)
    return document


def _attention(*records, conflicts=(), candidate_id="cand-1"):
    return {
        "candidates": [
            {
                "candidate_id": candidate_id,
                "conflicting_observation_keys": list(conflicts),
                "evidence": list(records),
            }
        ]
    }


def _build(attention, **kwargs):
    return brief.build_creative_experiment_brief(
        synthesis=kwargs.pop("synthesis", _synthesis()),
        consumer_attention=attention,
        target_geography=kwargs.pop("geography", "MX"),
        target_language=kwargs.pop("language", "es"),
        asserted_claims=kwargs.pop("asserted_claims", ()),
    )


def _authority(document):
    authority = document["authority"]
    assert authority["read_only"] is True
    assert authority["draft_only"] is True
    assert authority["planning_only"] is True
    for key in (
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
    ):
        assert authority[key] is False
    assert document["financial_fact"] is False
    assert document["audience_market"]["targeting_activated"] is False


def test_draft_links_problem_and_hypothesis_to_observed_attention():
    document = _build(_attention(_record()), synthesis=_synthesis(top_hooks=["show the collar before the meeting"]))
    assert document["schema"] == brief.SCHEMA
    assert document["outcome"] == "draft_brief"
    assert document["customer_problem"]["statement"] == "wrinkles before a meeting"
    assert document["customer_problem"]["product_fact"] is False
    assert document["customer_problem"]["evidence_refs"][0]["field"] == "pain_point"
    assert document["customer_problem"]["evidence_refs"][0]["evidence_mode"] == "observed"
    assert document["hypotheses"][0]["message"] == "show the collar before the meeting"
    assert document["hypotheses"][0]["status"] == "testable_draft"
    assert {item["field"] for item in document["hypotheses"][0]["evidence_refs"]} >= {"hook", "pain_point"}
    assert document["launch_draft_pack"]["reused"] is True
    assert document["launch_draft_pack"]["matrix_rows_linked_to_observed_hooks"] >= 1
    assert document["next_safe_step"] == "human_review_before_any_test_design"
    _authority(document)


def test_unsupported_claims_are_not_promoted():
    document = _build(
        _attention(_record()),
        asserted_claims=[UNSUPPORTED, "show the collar before the meeting"],
        synthesis=_synthesis(top_hooks=["show the collar before the meeting"], top_candidate_title=UNSUPPORTED),
    )
    assert document["outcome"] == "draft_brief"
    assert document["candidate_title"] is None
    rendered = json.dumps({"problem": document["customer_problem"], "hypotheses": document["hypotheses"]})
    assert UNSUPPORTED not in rendered
    assert document["claim_guardrails"]["unsupported_claims"] == [{"text": UNSUPPORTED, "reason": "unsupported_claim"}]
    assert document["claim_guardrails"]["product_claims_allowed"] is False
    assert "show the collar before the meeting" == document["hypotheses"][0]["message"]


def test_missing_attention_is_insufficient_and_ignores_pack_fallback():
    document = _build(None)
    assert document["outcome"] == "insufficient_evidence"
    assert "missing_attention_evidence" in document["insufficient_evidence_reasons"]
    assert document["customer_problem"] is None
    assert document["hypotheses"] == []
    rendered = json.dumps(document)
    assert "A common task still takes more effort" not in rendered
    assert "See Compact steamer in use" not in rendered
    assert document["launch_draft_pack"]["matrix_rows_not_used_as_facts"] >= 1
    assert document["next_safe_step"] == "collect_sanitized_attention_evidence_before_a_brief"
    _authority(document)


def test_contradictory_attention_is_not_settled():
    left = _record(observation_key="ship_days", observation_value="2", pain_point="ships in two days")
    right = _record(
        observation_key="ship_days", observation_value="20", pain_point="ships in twenty days", hook="wait three weeks"
    )
    document = _build(_attention(left, right, conflicts=["ship_days"]))
    assert document["outcome"] == "insufficient_evidence"
    assert "contradictory_attention_evidence" in document["insufficient_evidence_reasons"]
    assert document["conflicting_observation_keys"] == ["ship_days"]
    assert document["customer_problem"] is None
    assert document["hypotheses"] == []
    rendered = json.dumps(document)
    assert "ships in two days" not in rendered
    assert "ships in twenty days" not in rendered


def test_region_mismatch_blocks_the_brief():
    document = _build(_attention(_record(geography="US", pain_point="domestic shipping delay")))
    assert document["outcome"] == "insufficient_evidence"
    assert "region_mismatch" in document["insufficient_evidence_reasons"]
    assert document["audience_market"]["target_geography"] == "MX"
    assert "US" in document["audience_market"]["observed_geographies"]
    assert "domestic shipping delay" not in json.dumps(document["customer_problem"])
    assert document["hypotheses"] == []
    _authority(document)


def test_language_mismatch_blocks_the_brief():
    document = _build(_attention(_record(language="en", hook="show it in english")))
    assert document["outcome"] == "insufficient_evidence"
    assert "language_mismatch" in document["insufficient_evidence_reasons"]
    assert document["audience_market"]["target_language"] == "es"
    assert "en" in document["audience_market"]["observed_languages"]
    assert document["hypotheses"] == []
    assert "show it in english" not in json.dumps(document["hypotheses"])


def test_thresholds_stay_assumptions_and_lift_is_unevaluated():
    document = _build(_attention(_record()), synthesis=_synthesis(top_hooks=["show the collar before the meeting"]))
    kinds = {item["kind"] for item in document["measurement"]["thresholds"]}
    assert {"cpa", "ctr", "budget", "lift", "scale"} <= kinds
    for item in document["measurement"]["thresholds"]:
        assert item["label"] == "assumption"
        assert item["financial_fact"] is False
    lift = next(item for item in document["measurement"]["thresholds"] if item["kind"] == "lift")
    assert lift["value"] is None
    assert lift["status"] == "unevaluated"
    copied = next(item for item in document["measurement"]["thresholds"] if item["field"] == "kill_if_ctr_below")
    assert copied["value"] == 0.008
    assert copied["status"] == "copied_assumption"
    assert copied["copied_not_recomputed"] is True
    assert document["measurement"]["result_status"] == "not_measured"
    assert (
        "test_budget_is_a_rule_of_thumb_not_a_spend_authorization"
        in document["measurement"]["synthesis_assumption_labels"]
    )


def test_fixture_evidence_is_not_observed_fact():
    document = _build(_attention(_record(evidence_mode="fixture")))
    assert document["outcome"] == "insufficient_evidence"
    assert "missing_observed_attention" in document["insufficient_evidence_reasons"]
    assert document["customer_problem"] is None


def test_module_does_not_rescore_or_export():
    source = Path(brief.__file__).read_text(encoding="utf8")
    assert "calculate_offer_economics" not in source
    assert "build_product_opportunity_synthesis" not in source
    assert "append_report_events" not in source
    assert "client_workspace_isolation" not in source


def test_cli_rejects_secret_shaped_input(tmp_path: Path):
    synthesis = tmp_path / "synthesis.json"
    attention = tmp_path / "attention.json"
    synthesis.write_text(json.dumps(_synthesis()), encoding="utf8")
    attention.write_text(json.dumps({"access_token": "abcdefghijklmnop", "candidates": []}), encoding="utf8")
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_creative_experiment_brief.py"),
            "--synthesis",
            str(synthesis),
            "--attention",
            str(attention),
            "--geography",
            "MX",
            "--language",
            "es",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert completed.returncode == 2
    assert "abcdefghijklmnop" not in completed.stdout
    assert json.loads(completed.stdout)["error"] == "malformed creative brief input"


def _walk_keys(value):
    if isinstance(value, dict):
        yield from value
        for item in value.values():
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def _evidence(**extra):
    from evaluation.commerce.consumer_attention import ConsumerAttentionEvidence

    fields = {
        "candidate_id": "cand-1",
        "query": "compact steamer",
        "source": "fixture-note",
        "source_type": "fixture_demo",
        "platform": "manual",
        "evidence_mode": "observed",
        "pain_point": "wrinkles before a meeting",
        "hook": "show the collar before the meeting",
        "objection": "thick fabric may not respond",
        "angle": "demo",
        "geography": "MX",
        "language": "es",
        "observed_at": "2026-05-01T00:00:00Z",
    }
    fields.update(extra)
    return ConsumerAttentionEvidence(**fields)


def _report(*records, as_of="2026-06-01T00:00:00Z"):
    from evaluation.commerce.consumer_attention import build_report

    return build_report(list(records), evidence_mode="fixture", as_of=as_of).to_dict()


def _cli(tmp_path: Path, attention: dict) -> dict:
    folder = tmp_path / "case"
    folder.mkdir(parents=True)
    synthesis = folder / "synthesis.json"
    report = folder / "attention.json"
    synthesis.write_text(
        json.dumps(_synthesis(top_hooks=["show the collar before the meeting"])),
        encoding="utf8",
    )
    report.write_text(json.dumps(attention), encoding="utf8")
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_creative_experiment_brief.py"),
            "--synthesis",
            str(synthesis),
            "--attention",
            str(report),
            "--geography",
            "MX",
            "--language",
            "es",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert completed.returncode == 0, completed.stderr
    document = json.loads(completed.stdout)
    assert "observation_id" not in set(_walk_keys(document))
    _authority(document)
    return document


def test_cli_links_only_current_matching_attention(tmp_path: Path):
    fresh = _cli(tmp_path / "fresh", _report(_evidence()))
    assert fresh["outcome"] == "draft_brief"
    assert fresh["customer_problem"]["product_fact"] is False
    assert fresh["customer_problem"]["statement"] == "wrinkles before a meeting"
    ref = fresh["customer_problem"]["evidence_refs"][0]
    assert ref["source"] == "consumer_attention.candidates.evidence"
    assert ref["record_index"] == 0
    assert ref["field"] == "pain_point"
    assert ref["evidence_mode"] == "observed"
    assert set(ref) == {"source", "candidate_id", "record_index", "field", "evidence_mode"}
    assert fresh["hypotheses"][0]["product_fact"] is False
    assert fresh["hypotheses"][0]["status"] == "testable_draft"
    assert fresh["authority"]["spend_authorized"] is False
    assert fresh["authority"]["targeting_activated"] is False
    assert fresh["authority"]["published"] is False
    assert fresh["authority"]["customer_messages_sent"] is False
    assert fresh["authority"]["launch_authorized"] is False
    assert fresh["audience_market"]["targeting_activated"] is False

    missing = _cli(tmp_path / "missing", _report())
    assert missing["outcome"] == "insufficient_evidence"
    assert "missing_attention_evidence" in missing["insufficient_evidence_reasons"]
    assert missing["customer_problem"] is None
    assert missing["hypotheses"] == []

    stale = _cli(tmp_path / "stale", _report(_evidence(observed_at="2025-01-01T00:00:00Z")))
    assert stale["outcome"] == "insufficient_evidence"
    assert "stale_attention_evidence" in stale["insufficient_evidence_reasons"]
    assert stale["customer_problem"] is None
    assert stale["hypotheses"] == []
    assert "wrinkles before a meeting" not in json.dumps(stale["customer_problem"])
    assert "show the collar before the meeting" not in json.dumps(stale["hypotheses"])

    mixed = _report(
        _evidence(source="fresh-note", pain_point="fresh wrinkle note", hook="fresh collar hook"),
        _evidence(
            source="stale-note",
            observed_at="2025-01-01T00:00:00Z",
            pain_point="stale wrinkle note",
            hook="stale collar hook",
        ),
    )
    assert mixed["candidates"][0]["freshness_statuses"] == ["fresh", "stale"]
    mixed_brief = _cli(tmp_path / "mixed", mixed)
    assert mixed_brief["outcome"] == "insufficient_evidence"
    assert "stale_attention_evidence" in mixed_brief["insufficient_evidence_reasons"]
    assert mixed_brief["customer_problem"] is None
    rendered = json.dumps({"problem": mixed_brief["customer_problem"], "hypotheses": mixed_brief["hypotheses"]})
    assert "fresh wrinkle note" not in rendered
    assert "stale wrinkle note" not in rendered

    conflict = _cli(
        tmp_path / "conflict",
        _report(
            _evidence(
                source="left-note", observation_key="ship_days", observation_value="2", pain_point="ships in two days"
            ),
            _evidence(
                source="right-note",
                observation_key="ship_days",
                observation_value="20",
                pain_point="ships in twenty days",
                hook="wait three weeks",
            ),
        ),
    )
    assert conflict["outcome"] == "insufficient_evidence"
    assert "contradictory_attention_evidence" in conflict["insufficient_evidence_reasons"]
    assert conflict["conflicting_observation_keys"] == ["ship_days"]
    assert conflict["customer_problem"] is None
    assert conflict["hypotheses"] == []
    conflict_text = json.dumps({"problem": conflict["customer_problem"], "hypotheses": conflict["hypotheses"]})
    assert "ships in two days" not in conflict_text
    assert "ships in twenty days" not in conflict_text

    region = _cli(
        tmp_path / "region",
        _report(_evidence(geography="US", pain_point="domestic shipping delay")),
    )
    assert region["outcome"] == "insufficient_evidence"
    assert "region_mismatch" in region["insufficient_evidence_reasons"]
    assert region["customer_problem"] is None
    assert region["hypotheses"] == []
    assert "domestic shipping delay" not in json.dumps(region["customer_problem"])

    language = _cli(
        tmp_path / "language",
        _report(_evidence(language="en", hook="show it in english")),
    )
    assert language["outcome"] == "insufficient_evidence"
    assert "language_mismatch" in language["insufficient_evidence_reasons"]
    assert language["customer_problem"] is None
    assert language["hypotheses"] == []
    assert "show it in english" not in json.dumps(language["hypotheses"])
