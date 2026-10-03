"""Contract tests for the advisory OSS source intake catalog.

The intake file is not a source authority. These tests cover the validator
rules, the read-only defect report, and the committed catalog.
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ai.validate_oss_source_catalog import (  # noqa: E402
    build_report,
    collect_capability_defects,
    collect_registry_defects,
    is_all_zero_sha,
    is_exact_repository_url,
    is_patterned_placeholder_sha,
    render_markdown,
    REQUIRED_PROHIBITED_FLAGS,
    validate_paths,
)


INTAKE_PATH = REPO_ROOT / "data" / "oss_source_intake.json"
REGISTRY_PATH = REPO_ROOT / "data" / "source_adaptation_registry.json"
CAPABILITY_PATH = REPO_ROOT / "data" / "external_capability_catalog.json"
VALIDATOR_PATH = REPO_ROOT / "scripts" / "ai" / "validate_oss_source_catalog.py"
REAL_SHA = "ac6ebad10bedfb9111c4d95cda8a8831d28a31c5"
ZERO_SHA = "0" * 40
PLACEHOLDER_SHAS = {
    "src-coderos": "e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4",
    "src-gstack": "1a8b9c0d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b",
    "src-hermes-ecc": "3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d",
}
# The annotated tag object for src-scrapy 2.12.0 (peels to b1f9e56693cd2000ddcea922306f726f3e9339af).
ANNOTATED_TAG_SHA = "8c85937adef8279f12e35e0ee9a20c52ff6d1648"
SCRAPY_COMMIT_SHA = "b1f9e56693cd2000ddcea922306f726f3e9339af"


def _registry_row(source_id: str, sha: str) -> dict:
    return {"source_id": source_id, "repository_url": f"https://github.com/example/{source_id}", "revision": sha, "commit_sha": sha}


def _defective_registry() -> list[dict]:
    """The committed registry with one row per defect class the validator must keep detecting.

    Starting from the committed rows keeps every intake ``registry_ref`` resolvable, so the intake
    itself stays valid and only the registry defects change.
    """
    rows = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    bad_pins = {**PLACEHOLDER_SHAS, "src-scrapy": ANNOTATED_TAG_SHA}
    for row in rows:
        if row.get("source_id") in bad_pins:
            row["revision"] = row["commit_sha"] = bad_pins[row["source_id"]]
    return [
        *rows,
        _registry_row("src-zero", ZERO_SHA),
        _registry_row("src-clean", REAL_SHA),
        _registry_row("src-other-annotated", ANNOTATED_TAG_SHA),  # the annotated-tag rule is specific to src-scrapy
        "not a row",
        {"source_id": "src-no-pins"},
    ]


EXPECTED_DEFECTS = sorted(
    [
        (source_id, field, "patterned_placeholder_sha", sha)
        for source_id, sha in PLACEHOLDER_SHAS.items()
        for field in ("revision", "commit_sha")
    ]
    + [("src-scrapy", field, "annotated_tag_object_sha", ANNOTATED_TAG_SHA) for field in ("revision", "commit_sha")]
    + [("src-zero", field, "all_zero_sha", ZERO_SHA) for field in ("revision", "commit_sha")]
)


def _catalog(rows: list[dict]) -> dict:
    return {
        "schema_version": "oss-source-intake-v1",
        "catalog_status": "advisory_intake_only",
        "authority": "none",
        "observation_date": "2026-09-24",
        "candidates": rows,
    }


def _row(**overrides: object) -> dict:
    revision = str(overrides.get("revision", REAL_SHA))
    row = {
        "source_id": "oss-example",
        "repository_url": "https://github.com/example/library",
        "revision": revision,
        "version_tag": "v1.0.0",
        "license_evidence_url": f"https://github.com/example/library/blob/{revision}/LICENSE",
        "license": "Apache-2.0",
        "maintenance_evidence": "Observed 2026-09-24: contract fixture pin.",
        "relevant_module": "library/core.py",
        "work_order_id": "WO-C4-01",
        "marketos_target_capability": "offline fixture extraction",
        "verdict": "copy_pattern",
        "prohibited_behavior": "No live crawling, proxies, fingerprints, or credentials.",
        "prohibited_behavior_flags": list(REQUIRED_PROHIBITED_FLAGS),
        "security_tos_risks": "Fixture only. No network and no terms acceptance.",
        "attribution_requirement": "Retain the Apache-2.0 notice.",
        "duplicate_authority_decision": "Intake fixture, not a source authority.",
        "registry_ref": None,
        "confidence": "medium",
        "unknowns": "",
        "candidate_class": "oss_library",
    }
    row.update(overrides)
    if "revision" in overrides and "license_evidence_url" not in overrides:
        row["license_evidence_url"] = f"https://github.com/example/library/blob/{row['revision']}/LICENSE"
    return row


def _report(rows: list[dict], registry: list | None = None, capabilities: list | None = None) -> dict:
    return build_report(_catalog(rows), [] if registry is None else registry, [] if capabilities is None else capabilities)


def _errors(rows: list[dict], registry: list | None = None) -> list[str]:
    return _report(rows, registry=registry)["errors"]


def test_patterned_placeholder_detector_catches_known_shapes() -> None:
    for sha in PLACEHOLDER_SHAS.values():
        assert is_patterned_placeholder_sha(sha)
        assert is_patterned_placeholder_sha(sha[:10] + "0123456789abcdef0123456789")
    assert is_patterned_placeholder_sha("0123456789abcdef0123456789abcdef01234567")
    assert not is_patterned_placeholder_sha(REAL_SHA)
    assert not is_patterned_placeholder_sha(ZERO_SHA)
    assert is_all_zero_sha(ZERO_SHA)
    assert not is_all_zero_sha(REAL_SHA)


def test_valid_fixture_passes() -> None:
    report = _report([_row()])
    assert report["valid"] is True
    assert report["errors"] == []
    assert report["candidate_count"] == 1
    assert report["authority"] == "none"


def test_real_intake_file_validates() -> None:
    report, status = validate_paths(INTAKE_PATH, REGISTRY_PATH, CAPABILITY_PATH)
    assert status == 0
    assert report["valid"] is True
    assert report["errors"] == []
    assert report["candidate_count"] == 17
    document = json.loads(INTAKE_PATH.read_text(encoding="utf-8"))
    assert document["catalog_status"] == "advisory_intake_only"
    assert document["authority"] == "none"
    by_id = {row["source_id"]: row for row in document["candidates"]}
    assert by_id["oss-scrapy"]["registry_ref"] == "src-scrapy"
    assert by_id["oss-duckdb"]["registry_ref"] == "src-duckdb"
    assert by_id["oss-polars"]["registry_ref"] == "src-polars"
    for source_id in ("oss-scrapy", "oss-duckdb", "oss-polars"):
        assert by_id[source_id]["verdict"] is None
    assert by_id["oss-crawlee-python"]["repository_url"] == "https://github.com/apify/crawlee-python"
    assert by_id["oss-crawlee-python"]["license"] == "Apache-2.0"
    assert by_id["oss-crawlee-python"]["verdict"] == "copy_pattern"
    assert by_id["oss-crawlee-python"]["relevant_module"] == "src/crawlee/crawlers/_beautifulsoup/_beautifulsoup_parser.py"
    assert by_id["oss-trafilatura"]["license"] == "Apache-2.0"
    assert by_id["oss-trafilatura"]["verdict"] == "copy_pattern"
    assert by_id["oss-trafilatura"]["revision"] == "c1bc9531a2a978326112ca9987e1382745116136"
    assert by_id["oss-simpy"]["repository_url"] == "https://gitlab.com/team-simpy/simpy"
    assert by_id["oss-simpy"]["license"] == "MIT"
    assert by_id["oss-simpy"]["verdict"] == "copy_pattern"
    assert by_id["oss-un-comtrade-api-client"]["repository_url"] == "https://github.com/uncomtrade/comtradeapicall"
    assert by_id["oss-un-comtrade-api-client"]["license"] == "MIT"
    assert by_id["oss-un-comtrade-api-client"]["verdict"] == "defer"
    assert by_id["oss-un-comtrade-api-client"]["candidate_class"] == "external_api_client"
    assert by_id["oss-amazon-sp-api-models"]["verdict"] == "defer"
    assert by_id["oss-tiktok-business-api-sdk"]["verdict"] == "sidecar"
    assert by_id["oss-google-ads-python"]["verdict"] == "defer"
    for source_id in ("oss-amazon-sp-api-models", "oss-tiktok-business-api-sdk", "oss-google-ads-python"):
        assert by_id[source_id]["candidate_class"] == "platform_sdk"
    assert by_id["oss-meta-ad-library-scripts"]["verdict"] == "reference_only"
    assert by_id["oss-product-opportunity"]["verdict"] == "reference_only"
    assert by_id["oss-product-opportunity"]["license"] == "none_verified"
    assert by_id["oss-product-opportunity"]["repository_url"] is None
    assert by_id["oss-product-opportunity"]["revision"] is None
    assert by_id["oss-product-opportunity"]["license_evidence_url"] is None
    assert by_id["oss-product-opportunity"]["identity_unresolved"] is True
    assert by_id["oss-product-opportunity"]["candidate_class"] == "unidentified_namesake"
    assert by_id["oss-gapscope"]["verdict"] == "reference_only"
    assert by_id["oss-gapscope"]["repository_url"] is None
    assert by_id["oss-gapscope"]["revision"] is None
    assert by_id["oss-gapscope"]["identity_unresolved"] is True
    assert by_id["oss-gapscope"]["license"] == "none_verified"
    assert by_id["oss-speculora"]["verdict"] == "reference_only"
    assert by_id["oss-speculora"]["license"] == "CC-BY-4.0"
    assert by_id["oss-speculora"]["repository_url"] == "https://github.com/speculora/speculora"
    assert by_id["oss-ortools-dependency-weight"]["verdict"] == "defer"
    assert by_id["oss-ortools"]["verdict"] == "reference_only"
    counts: dict[str, int] = {}
    for row in document["candidates"]:
        if row.get("identity_unresolved") is True and row.get("repository_url") is None:
            assert row["verdict"] in {"reference_only", "reject"}
            assert row.get("revision") in (None, "")
        else:
            assert row["revision"] in row["license_evidence_url"]
            assert is_exact_repository_url(row["repository_url"])
        assert row["prohibited_behavior"].strip()
        assert row["prohibited_behavior_flags"] == list(REQUIRED_PROHIBITED_FLAGS)
        assert row["attribution_requirement"].strip()
        counts[row["work_order_id"]] = counts.get(row["work_order_id"], 0) + 1
    assert counts == report["work_order_counts"]
    assert all(count <= 5 for count in counts.values())


def _defect_tuples(defects: list[dict]) -> list[tuple]:
    return sorted((item["record_id"], item["field"], item["defect"], item["value"]) for item in defects)


def test_registry_defect_collector_reports_every_defect_class_and_only_those() -> None:
    defects = collect_registry_defects(_defective_registry())
    assert _defect_tuples(defects) == EXPECTED_DEFECTS
    assert all(item["record_kind"] == "source_adaptation_registry" for item in defects)
    assert defects == sorted(defects, key=lambda item: (item["record_id"], item["field"], item["defect"]))
    assert collect_registry_defects([_registry_row("src-clean", REAL_SHA)]) == []
    assert collect_registry_defects({"not": "a list"}) == [] and collect_registry_defects(None) == []


def test_registry_and_capability_defects_are_reported_without_failing(tmp_path: Path) -> None:
    """Defects in the registry or capability catalog are reported, never turned into a failing exit status."""
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(_defective_registry()), encoding="utf-8")
    report, status = validate_paths(INTAKE_PATH, registry_path, CAPABILITY_PATH)
    assert status == 0 and report["valid"] is True
    assert _defect_tuples(report["registry_defects"]) == EXPECTED_DEFECTS
    assert report["registry_defects"] == collect_registry_defects(json.loads(registry_path.read_text(encoding="utf-8")))
    found = {(item["record_id"], item["field"], item["value"]) for item in report["registry_defects"]}
    for source_id, sha in PLACEHOLDER_SHAS.items():
        assert (source_id, "revision", sha) in found
        assert (source_id, "commit_sha", sha) in found
    markdown = render_markdown(report)
    assert "src-scrapy" in markdown and "annotated_tag_object_sha" in markdown


def test_committed_registry_pins_are_real_commits_and_the_report_says_so() -> None:
    """The canonical registry was repaired (placeholder and annotated-tag pins replaced); keep it that way."""
    report, status = validate_paths(INTAKE_PATH, REGISTRY_PATH, CAPABILITY_PATH)
    assert status == 0 and report["valid"] is True
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert report["registry_defects"] == collect_registry_defects(registry) == []
    by_id = {row["source_id"]: row for row in registry if isinstance(row, dict)}
    for source_id, placeholder in PLACEHOLDER_SHAS.items():
        row = by_id[source_id]
        for field in ("revision", "commit_sha"):
            assert re.fullmatch(r"[0-9a-f]{40}", row[field]), (source_id, field)
            assert row[field] != placeholder and not is_patterned_placeholder_sha(row[field])
    assert by_id["src-scrapy"]["revision"] == by_id["src-scrapy"]["commit_sha"] == SCRAPY_COMMIT_SHA
    assert ANNOTATED_TAG_SHA not in json.dumps(registry)


def test_capability_catalog_zero_sha_defects_are_reported() -> None:
    report, _ = validate_paths(INTAKE_PATH, REGISTRY_PATH, CAPABILITY_PATH)
    capabilities = json.loads(CAPABILITY_PATH.read_text(encoding="utf-8"))
    assert report["capability_catalog_defects"] == collect_capability_defects(capabilities)
    zero_ids = {row["capability_id"] for row in capabilities if row.get("commit_sha") == ZERO_SHA}
    reported_ids = {item["capability_id"] for item in report["capability_catalog_defects"]}
    assert zero_ids == reported_ids
    assert "meta_ad_library" in reported_ids
    assert "tiktok_creative_center" in reported_ids
    assert len(reported_ids) == 15


def test_report_is_deterministic() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    capabilities = json.loads(CAPABILITY_PATH.read_text(encoding="utf-8"))
    intake = json.loads(INTAKE_PATH.read_text(encoding="utf-8"))
    first = build_report(intake, registry, capabilities)
    second = build_report(intake, registry, capabilities)
    assert first == second
    assert render_markdown(first) == render_markdown(second)
    assert "Canonical registry defects (reported, not fixed)" in render_markdown(first)
    encoded = json.dumps(first, indent=2, sort_keys=True)
    assert encoded == json.dumps(second, indent=2, sort_keys=True)


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"repository_url": "https://github.com/example/library.git"}, "repository URL is not exact"),
        ({"repository_url": "https://github.com/example/library/"}, "repository URL is not exact"),
        ({"repository_url": "http://github.com/example/library"}, "repository URL is not exact"),
        ({"repository_url": "https://github.com/example/library/tree/main"}, "repository URL is not exact"),
        ({"revision": ""}, "revision is empty"),
        ({"revision": "main"}, "revision is floating"),
        ({"revision": "master"}, "revision is floating"),
        ({"revision": "latest"}, "revision is floating"),
        ({"revision": "HEAD"}, "revision is floating"),
        ({"revision": ZERO_SHA}, "revision is all-zero"),
        ({"revision": PLACEHOLDER_SHAS["src-coderos"]}, "revision is a patterned placeholder"),
        ({"revision": "e5f6a7b8c9" + "ab" * 15}, "revision is a patterned placeholder"),
        ({"revision": "abc123"}, "revision is not a 40-character commit SHA"),
        ({"version_tag": "latest"}, "version_tag is floating"),
        ({"license": "GPL-3.0-only"}, "license blocks integrate/copy_pattern"),
        ({"license": "AGPL-3.0-only"}, "license blocks integrate/copy_pattern"),
        ({"license": "unknown"}, "license blocks integrate/copy_pattern"),
        ({"license": "missing", "verdict": "integrate"}, "license blocks integrate/copy_pattern"),
        ({"license_evidence_url": "https://github.com/example/library/blob/main/LICENSE"}, "primary LICENSE evidence URL"),
        ({"prohibited_behavior": "  "}, "prohibited_behavior is empty"),
        ({"attribution_requirement": ""}, "attribution_requirement is empty"),
        ({"candidate_class": "platform_sdk", "verdict": "integrate"}, "platform_sdk verdict must be sidecar or defer"),
        ({"candidate_class": "platform_sdk", "verdict": "copy_pattern"}, "platform_sdk verdict must be sidecar or defer"),
        ({"candidate_class": "external_api_client", "verdict": "copy_pattern"}, "external_api_client verdict must be sidecar or defer"),
        ({"registry_ref": "src-does-not-exist"}, "registry_ref does not exist"),
        ({"source_id": "src-scrapy"}, "source_id must use the oss- intake prefix"),
    ],
)
def test_each_violation_fails(overrides: dict, fragment: str) -> None:
    errors = _errors([_row(**overrides)])
    assert errors
    assert any(fragment in error for error in errors)


def test_exact_repository_url_accepts_gitlab_and_other_https_forges() -> None:
    assert is_exact_repository_url("https://gitlab.com/team-simpy/simpy")
    assert is_exact_repository_url("https://codeberg.org/example/library")
    assert is_exact_repository_url("https://bitbucket.org/example/library")
    assert not is_exact_repository_url("https://gitlab.com/team-simpy/simpy.git")
    assert not is_exact_repository_url("https://gitlab.com/team-simpy/simpy/")
    assert not is_exact_repository_url("http://gitlab.com/team-simpy/simpy")
    report = _report([_row(repository_url="https://codeberg.org/example/library")])
    assert report["valid"] is True


def _unresolved_row(**overrides: object) -> dict:
    row = _row(
        source_id="oss-unresolved-fixture",
        repository_url=None,
        revision=None,
        version_tag=None,
        license_evidence_url=None,
        license="none_verified",
        verdict="reference_only",
        identity_unresolved=True,
        candidate_class="unidentified_namesake",
        relevant_module="none",
        marketos_target_capability="none",
    )
    row.update(overrides)
    return row


def test_null_repository_url_only_for_unresolved_reference_or_reject() -> None:
    assert _report([_unresolved_row()])["valid"] is True
    assert _report([_unresolved_row(verdict="reject")])["valid"] is True
    for verdict in ("integrate", "copy_pattern", "sidecar"):
        errors = _errors([_unresolved_row(verdict=verdict, license="Apache-2.0")])
        assert any("null repository URL" in error for error in errors)
    omitted = _row(repository_url=None, verdict="reference_only", license="none_verified", license_evidence_url=None, revision=None)
    assert any("null repository URL" in error for error in _errors([omitted]))


def test_acceptance_negative_fixtures() -> None:
    """Each deliberately bad fixture must fail on its own."""
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    cases = {
        "zero SHA": (_report([_row(revision=ZERO_SHA)]), "revision is all-zero"),
        "patterned SHA": (_report([_row(revision=PLACEHOLDER_SHAS["src-coderos"])]), "revision is a patterned placeholder"),
        "main": (_report([_row(revision="main")]), "revision is floating"),
        "duplicate source_id": (
            _report([
                _row(source_id="oss-example"),
                _row(source_id="oss-example", repository_url="https://github.com/example/other"),
            ]),
            "duplicate source_id",
        ),
        "registry URL without registry_ref": (
            _report(
                [_row(repository_url="https://github.com/scrapy/scrapy", source_id="oss-scrapy-bare")],
                registry=registry,
            ),
            "repository URL is already in the source adaptation registry",
        ),
        "GPL integrate": (_report([_row(license="GPL-3.0-only", verdict="integrate")]), "license blocks integrate/copy_pattern"),
        "platform SDK integrate": (
            _report([_row(candidate_class="platform_sdk", verdict="integrate")]),
            "platform_sdk verdict must be sidecar or defer",
        ),
        "six candidates": (
            _report([
                _row(source_id=f"oss-extra-{index}", repository_url=f"https://github.com/example/lib{index}")
                for index in range(6)
            ]),
            "has more than 5 candidates (6)",
        ),
        "registry_ref with copy_pattern": (
            _report(
                [
                    _row(
                        repository_url="https://github.com/scrapy/scrapy",
                        source_id="oss-scrapy-verdict",
                        registry_ref="src-scrapy",
                        revision="b1f9e56693cd2000ddcea922306f726f3e9339af",
                        verdict="copy_pattern",
                    )
                ],
                registry=registry,
            ),
            "registry_ref row must have a null verdict",
        ),
        "null verdict without registry_ref": (
            _report([_row(registry_ref=None, verdict=None)]),
            "verdict is not an intake verdict",
        ),
    }
    for flag in REQUIRED_PROHIBITED_FLAGS:
        cases[f"missing {flag}"] = (
            _report([_row(prohibited_behavior_flags=[item for item in REQUIRED_PROHIBITED_FLAGS if item != flag])]),
            f"prohibited_behavior_flags missing {flag}",
        )
    cases["unknown prohibited flag"] = (
        _report([_row(prohibited_behavior_flags=[*REQUIRED_PROHIBITED_FLAGS, "live_scraping"])]),
        "prohibited_behavior_flags has unknown flag 'live_scraping'",
    )
    for name, (report, fragment) in cases.items():
        assert report["valid"] is False, name
        assert any(fragment in error for error in report["errors"]), name


@pytest.mark.parametrize("missing", REQUIRED_PROHIBITED_FLAGS)
def test_each_missing_prohibited_flag_fails_on_its_own(missing: str) -> None:
    flags = [flag for flag in REQUIRED_PROHIBITED_FLAGS if flag != missing]
    errors = _errors([_row(prohibited_behavior_flags=flags)])
    assert errors
    assert any(f"prohibited_behavior_flags missing {missing}" in error for error in errors)
    assert not any("unknown flag" in error for error in errors)


def test_unknown_prohibited_flag_fails() -> None:
    errors = _errors([_row(prohibited_behavior_flags=[*REQUIRED_PROHIBITED_FLAGS, "live_scraping"])])
    assert any("prohibited_behavior_flags has unknown flag 'live_scraping'" in error for error in errors)
    assert not any("prohibited_behavior_flags missing" in error for error in errors)


def test_duplicate_source_id_fails() -> None:
    errors = _errors([_row(source_id="oss-example"), _row(source_id="oss-example", repository_url="https://github.com/example/other")])
    assert any("duplicate source_id" in error for error in errors)


def test_more_than_five_candidates_fails() -> None:
    rows = [
        _row(source_id=f"oss-extra-{index}", repository_url=f"https://github.com/example/library{index}")
        for index in range(6)
    ]
    errors = _errors(rows)
    assert any("WO-C4-01 has more than 5 candidates (6)" in error for error in errors)


def test_gpl_reference_only_passes_and_copy_pattern_fails() -> None:
    copied = _report([_row(license="GPL-3.0-only", verdict="copy_pattern")])
    referenced = _report([_row(license="GPL-3.0-only", verdict="reference_only")])
    assert copied["valid"] is False
    assert referenced["valid"] is True


def test_permissive_copy_pattern_and_platform_sidecar_pass() -> None:
    report = _report(
        [
            _row(),
            _row(
                source_id="oss-platform",
                repository_url="https://github.com/example/ads-sdk",
                candidate_class="platform_sdk",
                verdict="sidecar",
                work_order_id="WO-C4-05",
            ),
            _row(
                source_id="oss-trade",
                repository_url="https://github.com/example/trade-client",
                candidate_class="external_api_client",
                verdict="defer",
                work_order_id="WO-C4-04",
            ),
        ]
    )
    assert report["valid"] is True


def test_registry_url_requires_matching_registry_ref() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    missing = _report(
        [_row(repository_url="https://github.com/scrapy/scrapy", source_id="oss-scrapy-copy")],
        registry=registry,
    )
    assert any("repository URL is already in the source adaptation registry" in error for error in missing["errors"])
    mismatched = _report(
        [_row(repository_url="https://github.com/scrapy/scrapy", source_id="oss-scrapy-copy", registry_ref="src-duckdb")],
        registry=registry,
    )
    assert any("registry_ref does not match repository URL" in error for error in mismatched["errors"])
    matched = _report(
        [
            _row(
                repository_url="https://github.com/scrapy/scrapy",
                source_id="oss-scrapy-pointer",
                registry_ref="src-scrapy",
                revision="b1f9e56693cd2000ddcea922306f726f3e9339af",
                verdict=None,
            )
        ],
        registry=registry,
    )
    assert matched["valid"] is True


def test_catalog_cannot_claim_authority() -> None:
    document = _catalog([_row()])
    document["catalog_status"] = "canonical"
    document["authority"] = "source_adaptation_registry"
    report = build_report(document, [], [])
    assert report["valid"] is False
    assert any("catalog_status must be advisory_intake_only" in error for error in report["errors"])
    assert any("authority must be none" in error for error in report["errors"])


def test_validator_module_has_no_network_imports() -> None:
    tree = ast.parse(VALIDATOR_PATH.read_text(encoding="utf-8"), filename=str(VALIDATOR_PATH))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    banned = {"socket", "urllib", "requests", "http", "httpx", "aiohttp", "subprocess", "ftplib", "smtplib"}
    assert imported.isdisjoint(banned)


def test_cli_json_exit_codes(tmp_path: Path) -> None:
    good = subprocess.run(
        [sys.executable, str(VALIDATOR_PATH), "--json", "--intake", str(INTAKE_PATH)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert good.returncode == 0
    payload = json.loads(good.stdout)
    assert payload["valid"] is True
    assert payload["registry_defects"] == [], "the committed registry carries no placeholder or annotated-tag pins"
    assert payload["capability_catalog_defects"]
    defective = tmp_path / "defective_registry.json"
    defective.write_text(json.dumps(_defective_registry()), encoding="utf-8")
    reported = subprocess.run(
        [sys.executable, str(VALIDATOR_PATH), "--json", "--intake", str(INTAKE_PATH), "--registry", str(defective)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert reported.returncode == 0, "registry defects are reported, not an exit failure"
    assert _defect_tuples(json.loads(reported.stdout)["registry_defects"]) == EXPECTED_DEFECTS
    missing = subprocess.run(
        [sys.executable, str(VALIDATOR_PATH), "--json", "--intake", str(tmp_path / "missing.json")],
        check=False,
        capture_output=True,
        text=True,
    )
    assert missing.returncode == 2
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps(_catalog([_row(revision="main")])), encoding="utf-8")
    bad = subprocess.run(
        [sys.executable, str(VALIDATOR_PATH), "--json", "--intake", str(bad_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert bad.returncode == 1
    assert json.loads(bad.stdout)["valid"] is False
    markdown = subprocess.run(
        [sys.executable, str(VALIDATOR_PATH), "--markdown", "--intake", str(INTAKE_PATH)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert markdown.returncode == 0
    assert markdown.stdout.startswith("# OSS source intake validation")
    again = subprocess.run(
        [sys.executable, str(VALIDATOR_PATH), "--markdown", "--intake", str(INTAKE_PATH)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert markdown.stdout == again.stdout
