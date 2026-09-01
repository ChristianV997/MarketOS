"""Tests for evaluation.commerce.serpapi_commerce_projection -- the thin,
offline downstream consumer of the existing SerpApi runtime adapter.

Every test stays fixture-only and offline: no network, no SDK, no
credential, no live transport. See docs/SERPAPI_COMMERCE_PROJECTION.md.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from evaluation.commerce.serpapi_commerce_projection import (
    EVIDENCE_TIER,
    FIXTURE_IDENTITY_LABEL,
    MAX_QUERY_LENGTH,
    SerpApiCommerceProjectionSafetySummary,
    build_serpapi_commerce_projection,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/serpapi_commerce_projection/serpapi_shopping_sample_dry_run.json"


# --- default projection / adapter reuse -----------------------------------------


def test_default_projection_reaches_dry_run_ready():
    report = build_serpapi_commerce_projection(query="widget")
    assert report.adapter_status == "dry_run_ready"
    assert report.adapter_readiness_state == "dry_run_ready"
    assert report.record_count == 1
    assert report.adapter_source == "serpapi_readonly_search"


def test_adapter_blockers_pass_through_unchanged():
    report = build_serpapi_commerce_projection(query="widget")
    assert "approval_missing" in report.adapter_blockers
    assert "terms_review_missing" in report.adapter_blockers
    assert "privacy_review_missing" in report.adapter_blockers


def test_caller_supplied_fixture_is_used():
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    report = build_serpapi_commerce_projection(query="insulated travel mug", fixture_payload=payload)
    assert report.record_count == 1
    assert report.records[0].candidate_id == "insulated-travel-mug"


# --- fixture identity labelling ---------------------------------------------------


def test_every_record_carries_explicit_fixture_identity_label():
    report = build_serpapi_commerce_projection(query="widget")
    for record in report.records:
        assert record.fixture_identity_label == FIXTURE_IDENTITY_LABEL
        assert record.evidence_tier == EVIDENCE_TIER
        assert record.source_provider == "serpapi"


# --- marketplace projection: explicit-only, never inferred ----------------------


def test_no_marketplace_projection_when_none_requested():
    report = build_serpapi_commerce_projection(query="widget")
    assert report.marketplace_requested is None
    assert report.marketplace_projection_applied is False
    for record in report.records:
        assert record.marketplace is None
        assert record.marketplace_evidence is None


def test_marketplace_projection_applied_only_for_explicit_supported_name():
    report = build_serpapi_commerce_projection(query="widget", marketplace="amazon")
    assert report.marketplace_requested == "amazon"
    assert report.marketplace_projection_applied is True
    record = report.records[0]
    assert record.marketplace == "amazon"
    assert record.marketplace_evidence is not None
    assert record.marketplace_evidence["marketplace"] == "amazon"
    assert record.marketplace_evidence["source_type"] == "fixture_demo"


def test_unsupported_marketplace_name_is_never_guessed_or_applied():
    """A caller naming something that isn't in
    evaluation.commerce.marketplace_trends.SUPPORTED must never be
    silently accepted or guessed into a real marketplace."""
    report = build_serpapi_commerce_projection(query="widget", marketplace="totally_made_up_site")
    assert report.marketplace_projection_applied is False
    assert report.records[0].marketplace is None
    assert report.records[0].marketplace_evidence is None


def test_generic_shopping_results_never_infer_a_marketplace():
    """The default (no marketplace named) path over generic
    google_shopping-shaped SerpApi data must never fabricate an Amazon,
    eBay, or other marketplace identity."""
    report = build_serpapi_commerce_projection(query="widget")
    for record in report.records:
        assert record.marketplace is None


# --- never a fourth Product Opportunity Synthesis pillar, never consumer-attention ---


def test_module_does_not_import_opportunity_synthesis_or_consumer_attention():
    import ast
    import inspect

    import evaluation.commerce.serpapi_commerce_projection as module

    source = inspect.getsource(module)
    tree = ast.parse(source)
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
    assert "evaluation.commerce.opportunity_synthesis" not in imported_modules
    assert "evaluation.commerce.consumer_attention" not in imported_modules


# --- no double-counting with DataForSEO -------------------------------------------


def test_module_never_imports_dataforseo():
    """Structural proof of non-double-counting: this module cannot combine
    or sum SerpApi and DataForSEO evidence because it never imports
    DataForSEO anywhere."""
    import ast
    import inspect

    import evaluation.commerce.serpapi_commerce_projection as module

    source = inspect.getsource(module)
    tree = ast.parse(source)
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module)
    assert not any("dataforseo" in name.lower() for name in imported_names)


def test_report_states_the_non_double_counting_note():
    report = build_serpapi_commerce_projection(query="widget")
    assert "consolidation-choice" in report.non_double_counting_note
    assert "dataforseo" in report.non_double_counting_note.lower()


# --- malformed / secret-like / raw payload / unbounded rejection -----------------


def test_oversized_query_is_rejected():
    with pytest.raises(ValueError):
        build_serpapi_commerce_projection(query="x" * (MAX_QUERY_LENGTH + 1))


def test_oversized_fixture_payload_record_count_is_rejected():
    """Regression: fixture_payload was previously only scanned for
    secret-shaped content, with no bound on size at all -- an oversized
    payload would have been processed in full."""
    from evaluation.commerce.serpapi_commerce_projection import MAX_FIXTURE_RECORDS

    payload = {
        "provider": "serpapi",
        "records": [{"candidate_id": f"item-{i}", "query": "q"} for i in range(MAX_FIXTURE_RECORDS + 1)],
        "fixture_mode": True,
    }
    with pytest.raises(ValueError):
        build_serpapi_commerce_projection(query="widget", fixture_payload=payload)


def test_oversized_fixture_payload_byte_size_is_rejected():
    from evaluation.commerce.serpapi_commerce_projection import MAX_FIXTURE_PAYLOAD_BYTES

    payload = {
        "provider": "serpapi",
        "records": [{"candidate_id": "x", "query": "q", "title": "y" * (MAX_FIXTURE_PAYLOAD_BYTES)}],
        "fixture_mode": True,
    }
    with pytest.raises(ValueError):
        build_serpapi_commerce_projection(query="widget", fixture_payload=payload)


def test_fixture_payload_within_bounds_is_accepted():
    payload = {"provider": "serpapi", "records": [{"candidate_id": "ok", "query": "q"}], "fixture_mode": True}
    report = build_serpapi_commerce_projection(query="widget", fixture_payload=payload)
    assert report.record_count == 1


def test_secret_like_fixture_payload_is_rejected_before_reaching_adapter():
    payload = {"provider": "serpapi", "records": [], "api_key": "sk-test-abcdefghijklmnopqrstuvwxyz"}
    with pytest.raises(ValueError):
        build_serpapi_commerce_projection(query="widget", fixture_payload=payload)


def test_raw_html_shaped_payload_is_rejected():
    payload = {"provider": "serpapi", "records": [{"candidate_id": "x", "title": "<html><body>evil</body></html>"}]}
    with pytest.raises(ValueError):
        build_serpapi_commerce_projection(query="widget", fixture_payload=payload)


def test_malformed_adapter_level_payload_fails_closed_via_adapter():
    """A payload valid enough to pass this module's own secret/HTML scan
    but malformed at the adapter's own contract level (records not a
    list) must still fail closed, via the adapter's own existing
    guarantee -- not reimplemented here."""
    payload = {"provider": "serpapi", "records": "not-a-list", "fixture_mode": True}
    report = build_serpapi_commerce_projection(query="widget", fixture_payload=payload)
    assert report.adapter_status == "error"
    assert report.record_count == 0


def test_empty_records_is_valid_not_an_error():
    payload = {"provider": "serpapi", "records": [], "fixture_mode": True}
    report = build_serpapi_commerce_projection(query="widget", fixture_payload=payload)
    assert report.adapter_status == "dry_run_ready"
    assert report.record_count == 0


# --- deterministic output ----------------------------------------------------------


def test_output_is_deterministic_across_calls():
    first = build_serpapi_commerce_projection(query="repeatable query").to_dict()
    second = build_serpapi_commerce_projection(query="repeatable query").to_dict()
    assert first == second


def test_generated_at_defaults_to_deterministic_sentinel_not_wall_clock():
    report = build_serpapi_commerce_projection(query="widget")
    assert report.generated_at == "offline-deterministic"


# --- safety summary ----------------------------------------------------------------


def test_safety_summary_is_read_only_and_fail_closed():
    report = build_serpapi_commerce_projection(query="widget")
    safety = report.safety_summary
    assert safety.read_only is True
    assert safety.network_calls is False
    assert safety.credentials_loaded is False
    assert safety.provider_calls is False
    assert safety.sdk_used is False
    assert safety.raw_payload_stored is False
    assert safety.raw_html_stored is False
    assert safety.external_actions is False
    assert safety.launch_authority is False
    assert safety.fail_closed is True


def test_safety_summary_cannot_be_constructed_unsafe():
    with pytest.raises(ValueError):
        SerpApiCommerceProjectionSafetySummary(
            read_only=True, network_calls=True, credentials_loaded=False, provider_calls=False,
            sdk_used=False, raw_payload_stored=False, raw_html_stored=False, external_actions=False,
            launch_authority=False, fail_closed=True,
        )


def test_module_imports_no_network_or_sdk_modules():
    import ast
    import inspect

    import evaluation.commerce.serpapi_commerce_projection as module

    source = inspect.getsource(module)
    tree = ast.parse(source)
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module.split(".")[0])
    forbidden = {
        "requests", "httpx", "urllib", "urllib3", "socket", "aiohttp", "boto3",
        "openai", "anthropic", "http", "ftplib", "smtplib", "telnetlib", "ssl",
        "subprocess", "grpc", "websocket", "websockets", "paramiko",
    }
    assert imported_names.isdisjoint(forbidden)


# --- CLI: no default write, --output writes, --json/--markdown ------------------


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/run_serpapi_commerce_projection.py"), *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30, check=False,
    )


def test_cli_json_output():
    result = _run_cli(["--json"])
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["report_version"]
    assert data["record_count"] == 1


def test_cli_markdown_output():
    result = _run_cli(["--markdown"])
    assert result.returncode == 0
    assert "# SerpApi Commerce Projection" in result.stdout


def test_cli_fixture_flag():
    result = _run_cli(["--fixture", "tests/fixtures/serpapi_commerce_projection/serpapi_shopping_sample_dry_run.json", "--json"])
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["records"][0]["candidate_id"] == "insulated-travel-mug"


def test_cli_default_never_writes_a_file(tmp_path):
    default_artifacts = ROOT / "artifacts" / "serpapi_commerce_projection"
    assert not default_artifacts.exists()
    result = _run_cli(["--json"])
    assert result.returncode == 0
    assert not default_artifacts.exists()


def test_cli_output_flag_writes_only_when_supplied(tmp_path):
    output_dir = tmp_path / "serpapi_projection_output"
    result = _run_cli(["--output", str(output_dir), "--markdown"])
    assert result.returncode == 0
    assert (output_dir / "serpapi_commerce_projection_report.json").is_file()
    assert (output_dir / "serpapi_commerce_projection_report.md").is_file()
    assert (output_dir / "serpapi_commerce_projection_records.json").is_file()


def test_cli_rejects_secret_like_fixture_file(tmp_path):
    secret_fixture = tmp_path / "secret.json"
    secret_fixture.write_text(json.dumps({"provider": "serpapi", "records": [], "api_key": "sk-test-abcdefghijklmnopqrstuvwxyz"}), encoding="utf-8")
    result = _run_cli(["--fixture", str(secret_fixture), "--json"])
    assert result.returncode == 2
    assert "serpapi_commerce_projection_error" in result.stderr


def test_cli_rejects_path_traversal_in_fixture_argument():
    result = _run_cli(["--fixture", "../../etc/passwd", "--json"])
    assert result.returncode == 2
