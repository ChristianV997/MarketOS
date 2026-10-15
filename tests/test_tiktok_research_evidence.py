"""Provider-specific tests for TikTok Research Tools evidence contract.

Fixture / fake transport only. No network, credentials, scraping, or edits to
owned TikTok legacy/route paths. See docs/TIKTOK_RESEARCH_EVIDENCE.md.
"""
from __future__ import annotations

import json
from pathlib import Path

from backend.adapters.research import tiktok_research_evidence as bridge
from backend.contracts.adapters import AdapterHealth, SidecarContext
from evaluation.commerce.tiktok_research_evidence import (
    ACCESS_DATE,
    COMMERCIAL_INELIGIBILITY,
    FakeTikTokResearchTransport,
    REPORT_VERSION,
    SOURCE,
    build_tiktok_research_evidence,
    official_citations,
    render_markdown,
    research_tool_capabilities,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "tiktok_research_evidence"
SANITIZED = FIXTURE_DIR / "sanitized_creative_snapshot.json"
PARTIAL = FIXTURE_DIR / "partial_missing_locale.json"
SECRET = FIXTURE_DIR / "secret_like_rejected.json"
RAW = FIXTURE_DIR / "raw_payload_rejected.json"


def _dry() -> SidecarContext:
    return SidecarContext(workspace_id="test-tiktok-research", run_id="run-1", dry_run=True)


def _live() -> SidecarContext:
    return SidecarContext(workspace_id="test-tiktok-research", run_id="run-1", dry_run=False)


def test_default_ordinary_runtime_is_blocked_and_empty():
    report = build_tiktok_research_evidence(observed_at=1_700_000_000.0)
    data = report.to_dict()
    assert data["report_version"] == REPORT_VERSION
    assert data["source"] == SOURCE
    assert data["capability_status"] == "blocked_ineligible_commercial_use"
    assert data["evidence_count"] == 0
    assert data["attention_report"] is None
    assert data["operational_capability"] is False
    assert data["eligible_live_source"] is None
    assert data["no_supported_commercial_attention_source"] is True
    assert data["execution_authorized"] is False
    assert data["network_calls"] is False
    assert data["live_provider_calls"] is False
    assert data["mutated"] is False
    assert data["client_visibility"] == "internal_only"
    assert data["authority"]["publish"] is False
    assert data["authority"]["spend"] is False
    assert data["authority"]["purchase_evidence"] is False
    assert data["authority"]["supplier_proof"] is False
    for blocker in COMMERCIAL_INELIGIBILITY:
        assert blocker in data["blockers"]
    assert all(surface["eligible_for_marketos_commercial_use"] is False for surface in data["surfaces"])
    assert all(surface["live_transport_implemented"] is False for surface in data["surfaces"])


def test_blocked_ineligible_mode_names_commercial_faq():
    report = build_tiktok_research_evidence(mode="blocked_ineligible_commercial_use")
    assert report.capability_status == "blocked_ineligible_commercial_use"
    assert "tiktok_faq_commercial_users_ineligible_for_research_tools" in report.blockers


def test_allow_live_always_blocked():
    report = build_tiktok_research_evidence(mode="fixture_demo", fixture_path=SANITIZED, allow_live=True)
    assert report.capability_status == "blocked_live_mode"
    assert report.evidence_count == 0
    assert "live_mode_requested" in report.blockers


def test_fixture_demo_builds_attention_without_network():
    report = build_tiktok_research_evidence(mode="fixture_demo", fixture_path=SANITIZED, allow_offline_demo=True, observed_at=1_700_000_000.0)
    data = report.to_dict()
    assert data["capability_status"] in {"fixture_demo", "partial"}
    assert data["evidence_count"] == 2
    assert data["network_calls"] is False
    assert data["live_provider_calls"] is False
    assert data["attention_report"] is not None
    assert data["attention_report"]["network_calls"] is False
    assert data["attention_report"]["mutated"] is False
    assert "research_tools_live_path_remains_blocked" in data["warnings"]
    platforms = data["attention_report"].get("platforms_observed") or []
    assert "tiktok" in platforms


def test_manual_import_mode_uses_ad_snapshot_source_type():
    report = build_tiktok_research_evidence(mode="manual_import", fixture_path=PARTIAL, allow_offline_demo=True)
    assert report.evidence_count == 1
    attention = report.attention_report or {}
    source_types: set[str] = set()
    for candidate in attention.get("candidates") or []:
        source_types.update(candidate.get("source_types") or [])
    assert "tiktok_ad_snapshot" in source_types


def test_fake_transport_success():
    rows = (
        {
            "candidate_id": "mini-thermal-printer",
            "query": "mini thermal printer",
            "platform": "tiktok",
            "hook": "Print labels from a phone",
            "view_count": "12000",
            "geography": "US",
            "language": "en",
            "observed_at": "2026-09-01T12:00:00Z",
        },
    )
    report = build_tiktok_research_evidence(
        mode="fake_transport",
        allow_offline_demo=True,
        transport=FakeTikTokResearchTransport(status="ok", rows=rows),
    )
    assert report.capability_status == "fake_transport_ok"
    assert report.evidence_count == 1
    assert "fake_transport_used_not_live" in report.warnings


def test_fake_transport_failure():
    report = build_tiktok_research_evidence(
        mode="fake_transport",
        allow_offline_demo=True,
        transport=FakeTikTokResearchTransport(status="rate_limited"),
    )
    assert report.capability_status == "fake_transport_error"
    assert report.evidence_count == 0
    assert any("http_status:429" in item for item in report.blockers)


def test_malformed_unsupported_mode():
    report = build_tiktok_research_evidence(mode="live_scrape")
    assert report.capability_status == "malformed_input"
    assert "unsupported_mode" in report.warnings


def test_secret_like_rows_rejected():
    report = build_tiktok_research_evidence(mode="fixture_demo", fixture_path=SECRET, allow_offline_demo=True)
    assert report.evidence_count == 0
    assert report.capability_status in {"malformed_input", "not_configured"}
    assert any("rejected_secret" in item for item in report.warnings)


def test_raw_payload_rows_rejected():
    report = build_tiktok_research_evidence(mode="fixture_demo", fixture_path=RAW, allow_offline_demo=True)
    assert report.evidence_count == 0
    assert any("rejected_raw_payload" in item for item in report.warnings)


def test_partial_missing_locale_preserved_as_unknown():
    report = build_tiktok_research_evidence(mode="manual_import", fixture_path=PARTIAL, allow_offline_demo=True)
    assert report.evidence_count == 1
    row = json.loads(PARTIAL.read_text(encoding="utf-8"))[0]
    from backend.adapters.research.consumer_attention import normalize_record

    item = normalize_record(row, default_platform="tiktok", default_source_type="tiktok_ad_snapshot", mode="manual_import")
    assert item is not None
    assert item.observed_at is None
    assert item.geography is None
    assert item.language is None


def test_stale_or_present_observed_at_not_invented():
    report = build_tiktok_research_evidence(mode="fixture_demo", fixture_path=SANITIZED, allow_offline_demo=True)
    attention = report.attention_report or {}
    observed = []
    for candidate in attention.get("candidates") or []:
        for evidence in candidate.get("evidence") or []:
            observed.append(evidence.get("observed_at"))
            assert evidence.get("geography") in {None, "US", "us"} or evidence.get("geography")
            assert evidence.get("platform") == "tiktok"
    assert any(value for value in observed)


def test_aggregate_only_no_personal_profile_fields():
    report = build_tiktok_research_evidence(mode="fixture_demo", fixture_path=SANITIZED, allow_offline_demo=True)
    blob = json.dumps(report.to_dict())
    for forbidden in ('"user_id"', '"follower_list"', '"email"', '"phone_number"', "lookalike", "oauth_token", "access_token"):
        assert forbidden not in blob.lower()
    assert report.authority["targeting_activated"] is False
    assert report.authority["ad_creation"] is False


def test_no_evidence_class_promotion_to_purchase_or_supplier():
    report = build_tiktok_research_evidence(mode="fixture_demo", fixture_path=SANITIZED, allow_offline_demo=True)
    assert report.authority["purchase_evidence"] is False
    assert report.authority["supplier_proof"] is False
    assert report.authority["product_demand"] is False
    assert report.authority["decision_scoring"] is False
    assumptions = set(report.assumptions)
    assert "tiktok_creative_or_ad_activity_is_not_purchase_intent" in assumptions
    assert "tiktok_attention_is_not_supplier_proof" in assumptions


def test_official_citations_include_faq_and_access_date():
    cites = official_citations()
    urls = {item["url"] for item in cites}
    assert "https://developers.tiktok.com/doc/research-api-faq" in urls
    assert "https://developers.tiktok.com/doc/commercial-content-api-getting-started" in urls
    assert "https://developers.tiktok.com/products/commercial-content-api" in urls
    assert "https://developers.tiktok.com/doc/commercial-content-api-supported-countries" in urls
    assert "https://developers.tiktok.com/products/research-api/" in urls
    assert all(item["access_date"] == ACCESS_DATE for item in cites)


def test_research_tool_capabilities_all_evaluated_surfaces_blocked():
    surfaces = research_tool_capabilities()
    names = {item.surface for item in surfaces}
    assert names == {"research_api", "commercial_content_api", "creative_center", "marketing_api"}
    assert all(not item.eligible_for_marketos_commercial_use for item in surfaces)
    assert all(not item.live_transport_implemented for item in surfaces)


def test_ccl_capability_does_not_assume_identical_research_api_eligibility():
    ccl = next(item for item in research_tool_capabilities() if item.surface == "commercial_content_api")
    joined = " ".join(ccl.notes)
    assert "same_eligibility_as_research_api" not in joined
    assert "do_not_assume_identical_research_api_eligibility_rule" in ccl.notes
    assert "supported_countries_eu_eea_uk_ch_mexico_not_listed" in ccl.notes
    assert "not_marketos_mexico_commercial_product_attention_source" in ccl.notes


def test_mexico_commercial_attention_boundary_blockers():
    report = build_tiktok_research_evidence()
    assert "mexico_commercial_product_attention_has_no_eligible_live_source" in report.blockers
    assert "commercial_content_api_eligibility_not_assumed_identical_to_research_api" in report.blockers
    assert "commercial_content_api_ad_geography_eu_eea_uk_ch_mexico_not_listed" in report.blockers
    assert "research_api_applicant_regions_exclude_mexico_per_products_page" in report.blockers
    assert report.evidence_count == 0
    assert report.operational_capability is False
    assert report.eligible_live_source is None


def test_render_markdown_includes_surfaces_and_citations():
    md = render_markdown(build_tiktok_research_evidence())
    assert "Capability status" in md
    assert "research_api" in md
    assert "commercial_content_api" in md
    assert "Research API FAQ" in md


def test_bridge_default_blocked_not_operational():
    evidence = bridge.fetch_research_evidence("mini thermal printer", context=_dry())
    assert evidence.status == "blocked_ineligible_commercial_use"
    assert evidence.evidence_count == 0
    assert evidence.commercial_eligible is False
    assert evidence.live_transport_implemented is False
    assert evidence.operational_capability is False


def test_bridge_fixture_demo():
    evidence = bridge.fetch_research_evidence(
        "mini thermal printer",
        context=_dry(),
        mode="fixture_demo",
        fixture_path=SANITIZED,
        allow_offline_demo=True,
    )
    assert evidence.evidence_count == 2
    assert evidence.status in {"fixture_demo", "partial"}
    payload = bridge.to_additional_evidence(evidence)
    assert payload["kind"] == "tiktok_research_tools_attention"
    assert payload["authority"]["spend"] is False
    assert payload["commercial_eligible"] is False


def test_bridge_live_context_blocked_empty_report():
    evidence = bridge.fetch_research_evidence("widget", context=_live(), mode="fixture_demo", fixture_path=SANITIZED, allow_offline_demo=True)
    assert evidence.status == "blocked_live_mode"
    assert evidence.evidence_count == 0
    assert evidence.report == {}
    assert "live_mode_requested" in evidence.blockers
    for prerequisite in bridge._LIVE_PREREQUISITES:
        assert prerequisite in evidence.blockers


def test_bridge_health_unreachable():
    health = bridge.health()
    assert isinstance(health, AdapterHealth)
    assert health.name == SOURCE
    assert health.reachable is False
    assert "blocked_commercial_ineligible" in health.capabilities
    assert "offline_demo_opt_in_only" in health.capabilities


def test_bridge_fake_transport_via_rows():
    evidence = bridge.fetch_research_evidence(
        "portable blender",
        context=_dry(),
        mode="fake_transport",
        allow_offline_demo=True,
        transport=FakeTikTokResearchTransport(
            status="ok",
            rows=(
                {
                    "candidate_id": "portable-blender",
                    "query": "portable blender",
                    "platform": "tiktok",
                    "hook": "Blend on the go",
                    "view_count": 5000,
                },
            ),
        ),
    )
    assert evidence.status == "fake_transport_ok"
    assert evidence.evidence_count == 1


def test_cli_default_blocked_zero_rows(capsys):
    from scripts.run_tiktok_research_evidence import main

    assert main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["capability_status"] == "blocked_ineligible_commercial_use"
    assert payload["evidence_count"] == 0
    assert payload["operational_capability"] is False


def test_cli_fixture_demo_requires_allow_flag(capsys):
    from scripts.run_tiktok_research_evidence import main

    assert main(["--mode", "fixture_demo", "--fixture", str(SANITIZED.relative_to(ROOT)), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["capability_status"] == "blocked_offline_demo_disabled"
    assert payload["evidence_count"] == 0

def test_cli_fixture_demo_with_allow_flag(capsys):
    from scripts.run_tiktok_research_evidence import main

    assert main(["--mode", "fixture_demo", "--allow-offline-demo", "--fixture", str(SANITIZED.relative_to(ROOT)), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["evidence_count"] == 2
    assert payload["operational_capability"] is False


def test_cli_allow_live_blocked(capsys):
    from scripts.run_tiktok_research_evidence import main

    assert main(["--allow-live", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["capability_status"] == "blocked_live_mode"


def test_cli_fake_error(capsys):
    from scripts.run_tiktok_research_evidence import main

    assert main(["--mode", "fake_transport", "--allow-offline-demo", "--fake-error", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["capability_status"] == "fake_transport_error"


def test_malformed_fixture_path(tmp_path: Path):
    bad = tmp_path / "not-json.txt"
    bad.write_text("nope", encoding="utf-8")
    report = build_tiktok_research_evidence(mode="fixture_demo", fixture_path=bad, allow_offline_demo=True)
    assert report.capability_status == "malformed_input"


def test_non_tiktok_platform_row_rejected():
    report = build_tiktok_research_evidence(
        mode="fixture_demo",
        allow_offline_demo=True,
        rows=[{"candidate_id": "x", "query": "x", "platform": "meta", "hook": "h", "view_count": 1}],
    )
    assert report.evidence_count == 0
    assert any("platform_not_tiktok" in item or "normalize_rejected" in item for item in report.warnings)


def test_offline_demo_without_flag_returns_zero_rows():
    report = build_tiktok_research_evidence(mode="fixture_demo", fixture_path=SANITIZED)
    assert report.capability_status == "blocked_offline_demo_disabled"
    assert report.evidence_count == 0
    assert report.operational_capability is False


def test_report_never_claims_operational_live_capability():
    for kwargs in (
        {},
        {"mode": "fixture_demo", "fixture_path": SANITIZED, "allow_offline_demo": True},
        {"allow_live": True},
    ):
        data = build_tiktok_research_evidence(**kwargs).to_dict()
        assert data["operational_capability"] is False
        assert data["eligible_live_source"] is None
        assert data["live_provider_calls"] is False
        assert data["network_calls"] is False
