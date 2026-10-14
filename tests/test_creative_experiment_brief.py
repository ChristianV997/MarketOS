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
    assert ref["schema"] == "MarketOS.CreativeEvidenceRef.v1"
    assert ref["source"] == "consumer_attention.candidates.evidence"
    assert ref["record_index"] == 0
    assert ref["field"] == "pain_point"
    assert ref["evidence_mode"] == "observed"
    assert ref["evidence_class"] == "observed"
    assert ref["freshness"] == "fresh"
    assert ref["conflict_state"] == "none"
    assert ref["observed_at"] == "2026-05-01T00:00:00Z"
    assert ref["geography"] == "MX"
    assert ref["language"] == "es"
    assert ref["source_reference"] == "fixture-note"
    assert ref["snapshot_digest_authenticates_source"] is False
    assert ref["report_snapshot_id"].startswith("snapshot:")
    assert ref["candidate_id_is_cross_source_identity"] is False
    assert ref["identity"]["linkage"] == "source_local_unlinked"
    assert "observation_id" not in ref["identity"]
    assert fresh["evidence_lineage"]["schema"] == "MarketOS.CreativeEvidenceLineage.v1"
    assert fresh["evidence_lineage"]["report_snapshot_id"] == ref["report_snapshot_id"]
    assert fresh["evidence_lineage"]["snapshot_digest_authenticates_source"] is False
    assert fresh["evidence_lineage"]["identity"]["linkage"] == "source_local_unlinked"
    assert fresh["evidence_lineage"]["identity"]["candidate_id_is_cross_source_identity"] is False
    assert fresh["hypotheses"][0]["evidence_refs"][0]["report_snapshot_id"] == ref["report_snapshot_id"]
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
    assert stale["evidence_lineage"]["freshness_statuses"] == ["stale"]
    assert stale["evidence_lineage"]["linked_fields"] == []
    assert "wrinkles before a meeting" not in json.dumps(stale["evidence_lineage"])
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


def _run_cli(tmp_path: Path, attention: dict, handoff: dict | None = None) -> subprocess.CompletedProcess[str]:
    folder = tmp_path / "case"
    folder.mkdir(parents=True)
    synthesis = folder / "synthesis.json"
    report = folder / "attention.json"
    synthesis.write_text(
        json.dumps(_synthesis(top_hooks=["show the collar before the meeting"])),
        encoding="utf8",
    )
    report.write_text(json.dumps(attention), encoding="utf8")
    command = [
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
    ]
    if handoff is not None:
        path = folder / "handoff.json"
        path.write_text(json.dumps(handoff), encoding="utf8")
        command.extend(["--identity-handoff", str(path)])
    return subprocess.run(command, check=False, capture_output=True, text=True, cwd=ROOT)


def _manual_attention(**extra):
    record = {
        "candidate_id": "cand-1",
        "pain_point": "wrinkles before a meeting",
        "hook": "show the collar before the meeting",
        "objection": "thick fabric may not respond",
        "angle": "demo",
        "geography": "MX",
        "language": "es",
        "evidence_mode": "observed",
        "observed_at": "2026-05-01T00:00:00Z",
        "source": "fixture-note",
    }
    record.update(extra)
    return {
        "candidates": [
            {
                "candidate_id": "cand-1",
                "freshness_statuses": ["fresh"],
                "conflicting_observation_keys": [],
                "evidence": [record],
            }
        ]
    }


def test_cli_identity_boundary_does_not_invent_observation_ids(tmp_path: Path):
    insight = {
        "insight_id": "theme:cand-1:demo",
        "candidate_id": "cand-1",
        "kind": "demand_theme",
        "statement": "insight-only phrase about steamers",
        "signal_family": "review",
        "sources": ["fixture-note"],
        "platforms": ["manual"],
        "geographies": ["MX"],
        "languages": ["es"],
        "observation_window": {
            "earliest": None,
            "latest": None,
            "freshness": ["fresh"],
            "missing_time_count": 0,
            "as_of": None,
        },
        "aggregate_counts": {"evidence_count": 1},
        "evidence_class": "observed",
        "uncertainty": [],
        "contradictions": [],
        "unsupported_claims": [],
        "supporting_excerpts": [],
    }
    hinted = brief.build_creative_experiment_brief(
        synthesis=_synthesis(top_hooks=["show the collar before the meeting"]),
        consumer_attention=_report(_evidence()),
        target_geography="MX",
        target_language="es",
        identity_handoff={
            "contract_version": "product-identity-synthesis-handoff-v1",
            "candidate_id_hint_is_not_exact_basis": True,
            "by_observation_id": {"cand-1": {"match_state": "exact_match", "candidate_key": "ck-from-candidate-id"}},
        },
        consumer_insights=insight,
    )
    rendered = json.dumps(hinted)
    assert hinted["outcome"] == "draft_brief"
    assert hinted["evidence_lineage"]["identity"]["linkage"] == "source_local_unlinked"
    assert hinted["evidence_lineage"]["insight_boundary"]["observation_id_present"] is False
    assert hinted["evidence_lineage"]["insight_boundary"]["statements_used_as_hypotheses"] is False
    assert hinted["evidence_lineage"]["identity"]["required_upstream_contract"]["name"] == (
        "product-identity-synthesis-handoff-v1"
    )
    assert "insight-only phrase about steamers" not in rendered
    assert "ck-from-candidate-id" not in rendered
    assert "observation_id" not in set(_walk_keys(hinted))

    exact_handoff = {
        "contract_version": "product-identity-synthesis-handoff-v1",
        "auto_merge_allowed_states": ["exact_match"],
        "by_observation_id": {"obs-exact-1": {"match_state": "exact_match", "candidate_key": "ck-exact-1"}},
    }
    exact_run = _run_cli(tmp_path / "exact", _manual_attention(observation_id="obs-exact-1"), exact_handoff)
    assert exact_run.returncode == 0, exact_run.stderr
    exact = json.loads(exact_run.stdout)
    identity = exact["hypotheses"][0]["evidence_refs"][0]["identity"]
    assert identity["linkage"] == "exact_match"
    assert identity["observation_id"] == "obs-exact-1"
    assert identity["candidate_key"] == "ck-exact-1"
    assert identity["candidate_id_is_cross_source_identity"] is False
    assert exact["evidence_lineage"]["identity"]["linkage"] == "exact_match"
    _authority(exact)

    possible = {
        "contract_version": "product-identity-synthesis-handoff-v1",
        "by_observation_id": {"obs-exact-1": {"match_state": "possible_match", "candidate_key": "ck-maybe"}},
    }
    possible_run = _run_cli(tmp_path / "possible", _manual_attention(observation_id="obs-exact-1"), possible)
    assert possible_run.returncode == 0, possible_run.stderr
    possible_doc = json.loads(possible_run.stdout)
    assert possible_doc["evidence_lineage"]["identity"]["linkage"] == "source_local_unlinked"
    assert "ck-maybe" not in possible_run.stdout
    assert possible_doc["hypotheses"][0]["evidence_refs"][0]["identity"]["linkage"] == "source_local_unlinked"

    marker = "OVERSIZE-MARKER-9f3a"
    oversized = _run_cli(tmp_path / "oversize", _manual_attention(source=("S" * 100) + marker))
    assert oversized.returncode == 0, oversized.stderr
    oversized_doc = json.loads(oversized.stdout)
    assert marker not in oversized.stdout
    assert oversized_doc["hypotheses"][0]["evidence_refs"][0]["source_reference"] is None

    canary = "lineage-canary@example.com"
    leaked = _run_cli(tmp_path / "canary", _manual_attention(pain_point=canary))
    assert leaked.returncode == 2
    assert canary not in leaked.stdout
    assert canary not in leaked.stderr
    assert json.loads(leaked.stdout)["error"] == "malformed creative brief input"

    phone = _run_cli(tmp_path / "phone", _manual_attention(objection="call 555-010-0199"))
    assert phone.returncode == 2
    assert "555-010-0199" not in phone.stdout

    malformed = _run_cli(
        tmp_path / "malformed",
        _manual_attention(),
        {"by_observation_id": ["MALFORMED-HANDOFF-BLOB-7731"]},
    )
    assert malformed.returncode == 2
    assert "MALFORMED-HANDOFF-BLOB-7731" not in malformed.stdout

    huge_id = "o" * 90
    huge = _run_cli(tmp_path / "huge-id", _manual_attention(observation_id=huge_id), exact_handoff)
    assert huge.returncode == 2
    assert huge_id not in huge.stdout

    supplied = _manual_attention()
    supplied["report_snapshot_id"] = "snapshot:" + ("ab" * 16)
    supplied_run = _run_cli(tmp_path / "supplied", supplied)
    assert supplied_run.returncode == 0, supplied_run.stderr
    supplied_doc = json.loads(supplied_run.stdout)
    assert supplied_doc["evidence_lineage"]["supplied_report_snapshot_id"] == supplied["report_snapshot_id"]
    assert supplied_doc["evidence_lineage"]["report_snapshot_id"] != supplied["report_snapshot_id"]
    again = _run_cli(tmp_path / "supplied-again", supplied)
    assert (
        json.loads(again.stdout)["evidence_lineage"]["snapshot_digest"]
        == (supplied_doc["evidence_lineage"]["snapshot_digest"])
    )
