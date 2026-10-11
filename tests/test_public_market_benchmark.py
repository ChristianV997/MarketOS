from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.run_phase1_public_market_benchmark as cli
from backend.adapters.research.competition_evidence import CompetitorOffer
from evaluation.commerce.public_market_benchmark import (
    _safe_url,
    build_public_market_benchmark,
    load_public_market_seed,
    markdown_report,
    redact_report_urls,
    synthesize_from_public_market,
    to_marketplace_trend_report,
)
from scripts.run_phase1_public_market_benchmark import main


ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "tests" / "fixtures" / "public_market_benchmark" / "candidates.json"


def test_fixture_seed_is_bounded_and_deterministic():
    candidates, warnings = load_public_market_seed(SEED)
    one = build_public_market_benchmark(candidates, max_candidates=3).to_dict()
    two = build_public_market_benchmark(candidates, max_candidates=3).to_dict()
    assert not warnings
    assert one == two
    assert one["network_used"] is False
    assert one["competitor_offers_observed"] == 3
    assert one["top_candidate_from_public_market"] == "mini-thermal-printer"


def test_fixture_evidence_is_explicitly_not_live_proof():
    candidates, _ = load_public_market_seed(SEED)
    report = build_public_market_benchmark(candidates, max_candidates=1).to_dict()
    assert report["evidence_mode"] == "fixture_demo"
    assert report["warnings"] == ["fixture_demo_evidence_only_not_live_proof"]
    assert report["next_best_action"].startswith("set_cj_credentials_and_validate_candidate:")
    assert "supplier" in report["remaining_supplier_blocker"]


def test_live_mode_is_bounded_and_uses_injected_fetcher_only():
    candidates, _ = load_public_market_seed(SEED)
    calls: list[str] = []
    def fetch(url: str, *, context):
        calls.append(url)
        return CompetitorOffer("fixture", url, 1.0, "listing", "Observed offer", {"title": "observed", "price": "observed"}, price=42.0, confidence=0.6)
    report = build_public_market_benchmark(candidates, allow_network=True, max_candidates=1, max_competitors_per_candidate=1, fetcher=fetch).to_dict()
    assert calls == ["https://example-shop.test/products/mini-printer"]
    assert report["network_used"] is True
    assert report["competitor_pages_attempted"] == 1
    assert report["competitor_offers_observed"] == 1


def test_sanitized_evidence_removes_url_query_values():
    candidate = {"candidate_id": "safe", "title": "Safe", "query": "safe", "category": "test", "competitor_urls": [], "fixture_offers": [{"competitor_url": "https://public.example/p?a=secret-token", "source_domain": "public.example", "product_title": "Safe", "price": 1.0, "source_confidence": 1.0}]}
    evidence = build_public_market_benchmark([candidate]).to_dict()["candidate_results"][0]["evidence"][0]
    assert evidence["competitor_url"] == "https://public.example/p"
    assert "secret-token" not in json.dumps(evidence)


def test_malformed_seed_degrades_without_crashing(tmp_path: Path):
    path = tmp_path / "bad.json"; path.write_text("not-json", encoding="utf-8")
    candidates, warnings = load_public_market_seed(path)
    assert candidates == []
    assert warnings == ["candidate_seed_unavailable:JSONDecodeError"]


def test_markdown_has_no_raw_html_or_authority_claim():
    candidates, _ = load_public_market_seed(SEED)
    rendered = markdown_report(build_public_market_benchmark(candidates, max_candidates=2).to_dict())
    assert "Public-market evidence is read-only market context" in rendered
    assert "<html" not in rendered.lower()


@pytest.fixture
def artifacts_root(tmp_path: Path, monkeypatch) -> Path:
    """Stand-in artifacts/ root so every CLI write stays under tmp_path."""
    root = (tmp_path / "artifacts").resolve()
    root.mkdir()
    monkeypatch.setattr(cli, "ARTIFACTS", root)
    return root


def test_cli_writes_only_when_output_is_explicit(artifacts_root: Path, capsys):
    output = artifacts_root / "report"
    assert main(["--candidate-seed", str(SEED), "--output", str(output), "--json"]) == 0
    assert (output / "public_market_benchmark_report.json").is_file()
    assert (output / "benchmark_matrix_report.json").is_file()
    assert (output / "readiness_summary.json").is_file()
    assert (output / "marketplace_trend_report.json").is_file()
    assert (output / "opportunity_synthesis_report.json").is_file()
    marketplace = json.loads((output / "marketplace_trend_report.json").read_text(encoding="utf-8"))
    synthesis = json.loads((output / "opportunity_synthesis_report.json").read_text(encoding="utf-8"))
    assert marketplace["candidate_count"] >= 1
    assert "projected_from_public_market_benchmark" in marketplace["warnings"]
    assert synthesis["overall_recommendation"] == "validate_supplier_first"
    assert synthesis["source_reports"]["supplier"] == "missing"
    assert "fixture_demo" in capsys.readouterr().out


def test_public_market_projects_into_marketplace_pillar_without_supplier_authority():
    candidates, _ = load_public_market_seed(SEED)
    report = build_public_market_benchmark(candidates, max_candidates=3).to_dict()
    marketplace = to_marketplace_trend_report(report).to_dict()
    assert marketplace["network_calls"] is False
    assert marketplace["mutated"] is False
    assert marketplace["candidate_count"] == 3
    assert marketplace["top_candidate_id"]
    assert "marketplace_evidence_is_not_supplier_proof" in marketplace["warnings"]
    assert "projected_from_public_market_benchmark" in marketplace["warnings"]
    leader = marketplace["candidates"][0]
    assert leader["score"]["overall_marketplace_opportunity"] > 0
    assert leader["score"]["recommendation"] == "validate_supplier_first"
    assert any(item["price"] is not None for item in leader["evidence"])


def test_synthesize_from_public_market_reuses_canonical_three_pillar_layer():
    candidates, _ = load_public_market_seed(SEED)
    report = build_public_market_benchmark(candidates, max_candidates=3).to_dict()
    synthesis = synthesize_from_public_market(report).to_dict()
    assert synthesis["overall_recommendation"] == "validate_supplier_first"
    assert synthesis["marketplace_opportunity"] > 0
    assert synthesis["supplier_feasibility"] == 0.0
    assert synthesis["consumer_attention"] == 0.0
    assert synthesis["source_reports"] == {
        "marketplace": "supplied",
        "supplier": "missing",
        "consumer_attention": "missing",
        "product_validation": "missing",
    }
    assert synthesis["confidence_grade"] == "D_low_confidence"
    assumptions = synthesis["decision_thresholds"].get("assumptions") or []
    assert "ctr_and_add_to_cart_thresholds_are_planning_assumptions" in assumptions
    assert synthesis["decision_thresholds"].get("supplier_validation_required") is True


# --- URL sanitization: userinfo, query and fragment never reach a report -----------------------

_USER, _PASSWORD, _TOKEN, _FRAGMENT = "canaryuser", "canarysecretpw", "querycanary", "fragcanary"
_STEM = "canary"  # shared by every synthetic canary, so truncated fragments are caught too
_USERINFO_URL = f"https://{_USER}:{_PASSWORD}@public.example/p/widget?tok={_TOKEN}#{_FRAGMENT}"


def _candidate(**overrides) -> dict:
    value = {
        "candidate_id": "safe", "title": "Safe", "query": "safe", "category": "test", "competitor_urls": [],
        "fixture_offers": [{"competitor_url": _USERINFO_URL, "source_domain": f"{_USER}:{_PASSWORD}@public.example", "product_title": "Safe", "price": 9.0, "source_confidence": 0.9}],
    }
    value.update(overrides)
    return value


def _assert_no_canary(value: object) -> None:
    blob = value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)
    assert _STEM not in blob


def _priced_offer(url: str, *, warnings: tuple[str, ...] = ()) -> CompetitorOffer:
    return CompetitorOffer("fixture", url, 1.0, "listing", "Observed offer", {"title": "observed", "price": "observed"}, price=42.0, confidence=0.6, warnings=warnings)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (_USERINFO_URL, "https://public.example/p/widget"),
        (f"https://{_USER}@public.example:8443/p", "https://public.example:8443/p"),
        (f"https://{_USER}:p@ss@public.example/p?x=1", "https://public.example/p"),
        ("https://[::1]:8080/x?a=1", "https://[::1]:8080/x"),
        ("ftp://public.example/p", ""),
        ("https://", ""),
        ("https://[unterminated/p", ""),
        (None, ""),
    ],
)
def test_safe_url_keeps_only_scheme_host_port_and_path(raw, expected):
    assert _safe_url(raw) == expected


def test_fixture_report_never_echoes_url_userinfo_in_any_projection():
    report = build_public_market_benchmark([_candidate()]).to_dict()
    marketplace = to_marketplace_trend_report(report).to_dict()
    synthesis = synthesize_from_public_market(report).to_dict()
    _assert_no_canary([report, marketplace, synthesis])
    _assert_no_canary(markdown_report({**report, "marketplace_trend_report": marketplace, "opportunity_synthesis": synthesis}))
    evidence = report["candidate_results"][0]["evidence"][0]
    assert evidence["competitor_url"] == "https://public.example/p/widget"
    assert evidence["source_domain"] == "public.example"
    assert marketplace["candidates"][0]["evidence"][0]["source_url"] == "https://public.example/p/widget"


def test_live_mode_never_hands_userinfo_urls_to_the_fetcher():
    clean = "https://public.example/clean"
    candidate = _candidate(fixture_offers=[], competitor_urls=[_USERINFO_URL, clean])
    calls: list[str] = []
    def fetch(url: str, *, context):
        calls.append(url)
        return _priced_offer(url)
    report = build_public_market_benchmark([candidate], allow_network=True, fetcher=fetch).to_dict()
    assert calls == [clean]
    assert report["competitor_pages_attempted"] == 1
    assert "competitor_url_with_userinfo_rejected" in report["warnings"]
    _assert_no_canary(report)


def test_live_mode_with_only_userinfo_urls_makes_no_fetch_and_no_claim():
    candidate = _candidate(fixture_offers=[], competitor_urls=[_USERINFO_URL])
    def fetch(url: str, *, context):
        raise AssertionError("a userinfo URL reached the fetcher")
    report = build_public_market_benchmark([candidate], allow_network=True, fetcher=fetch).to_dict()
    assert report["competitor_pages_attempted"] == 0
    assert report["competitor_offers_observed"] == 0
    _assert_no_canary(report)


@pytest.mark.parametrize("padding", [0, 120, 148, 150])
def test_adapter_warnings_that_echo_a_url_are_sanitized_before_truncation(padding: int):
    # The adapter reports e.g. "robots.txt disallows evidence URL: <url>"; the report must not keep the secret
    # parts, including when the 180-character cap would otherwise cut the URL mid-credential.
    echoed = "w" * padding + " " + _USERINFO_URL
    candidate = _candidate(fixture_offers=[], competitor_urls=["https://public.example/a"])
    def fetch(url: str, *, context):
        return _priced_offer(url, warnings=(f"robots_blocked:{echoed}",))
    report = build_public_market_benchmark([candidate], allow_network=True, fetcher=fetch).to_dict()
    _assert_no_canary(report)
    _assert_no_canary(markdown_report(report))
    assert report["candidate_results"][0]["evidence"][0]["warnings"]


def test_redact_report_urls_is_structure_preserving_and_idempotent():
    stored = {"a": [{"competitor_url": _USERINFO_URL, "warnings": (f"see {_USERINFO_URL}.",)}], "n": 3, "t": "no url here", "flag": True}
    once = redact_report_urls(stored)
    _assert_no_canary(once)
    assert once["n"] == 3 and once["t"] == "no url here" and once["flag"] is True
    assert once["a"][0]["competitor_url"] == "https://public.example/p/widget"
    assert redact_report_urls(once) == once


# --- CLI: --output stays under artifacts/, --allow-network is the only path to the fetcher -----

def _all_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def test_cli_without_output_writes_nothing(monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise AssertionError("the CLI wrote without --output")
    monkeypatch.setattr(cli, "_write", boom)
    assert main(["--candidate-seed", str(SEED), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["evidence_mode"] == "fixture_demo"


@pytest.mark.parametrize("target", ["outside", "dotdot", "artifacts_root", "sibling_prefix", "victim_file"])
def test_cli_rejects_output_outside_artifacts_before_any_work(tmp_path: Path, artifacts_root: Path, monkeypatch, capsys, target: str):
    victim = tmp_path / "victim.py"
    victim.write_text("# sentinel\n", encoding="utf-8")
    chosen = {
        "outside": tmp_path / "outside" / "run",
        "dotdot": artifacts_root / ".." / "escaped",
        "artifacts_root": artifacts_root,
        "sibling_prefix": tmp_path / "artifacts-evil" / "run",
        "victim_file": victim,
    }[target]
    def boom(*args, **kwargs):
        raise AssertionError("work started before --output was validated")
    monkeypatch.setattr(cli, "build_public_market_benchmark", boom)
    before = _all_files(tmp_path)
    with pytest.raises(SystemExit) as exit_info:
        main(["--candidate-seed", str(SEED), "--output", str(chosen), "--json"])
    assert exit_info.value.code == 2
    assert "artifacts" in capsys.readouterr().err
    assert _all_files(tmp_path) == before
    assert victim.read_text(encoding="utf-8") == "# sentinel\n"


def test_cli_rejects_a_symlink_that_escapes_artifacts(tmp_path: Path, artifacts_root: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (artifacts_root / "link").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"NOT COVERED: symlinks unavailable on this host ({type(exc).__name__})")
    with pytest.raises(SystemExit) as exit_info:
        main(["--candidate-seed", str(SEED), "--output", str(artifacts_root / "link" / "run"), "--json"])
    assert exit_info.value.code == 2
    assert _all_files(outside) == []


def test_cli_accepts_a_single_json_file_under_artifacts(artifacts_root: Path, capsys):
    target = artifacts_root / "phase1" / "latest.json"
    assert main(["--candidate-seed", str(SEED), "--output", str(target), "--json"]) == 0
    capsys.readouterr()
    assert json.loads(target.read_text(encoding="utf-8"))["evidence_mode"] == "fixture_demo"
    assert _all_files(artifacts_root) == [target]


def _spy_on_builder(monkeypatch, fetch):
    """Record the CLI's builder kwargs and inject a stub fetcher so no test can reach the network."""
    seen: list[dict] = []
    real = cli.build_public_market_benchmark
    def spy(candidates, **kwargs):
        seen.append(kwargs)
        return real(candidates, fetcher=fetch, **kwargs)
    monkeypatch.setattr(cli, "build_public_market_benchmark", spy)
    return seen


def test_cli_default_never_reaches_the_fetcher_and_is_not_supplier_proof(monkeypatch, capsys):
    def fetch(url: str, *, context):
        raise AssertionError("the default CLI path reached the fetcher")
    seen = _spy_on_builder(monkeypatch, fetch)
    assert main(["--candidate-seed", str(SEED), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert [item["allow_network"] for item in seen] == [False]
    assert report["evidence_mode"] == "fixture_demo" and report["network_used"] is False
    assert report["read_only"] is True and report["mutated"] is False and report["credentials_required"] is False
    assert "fixture_demo_evidence_only_not_live_proof" in report["warnings"]
    assert report["remaining_supplier_blocker"] == "authenticated_supplier_evidence_not_live_observed"
    assert report["marketplace_trend_report"]["network_calls"] is False
    assert report["opportunity_synthesis"]["source_reports"]["supplier"] == "missing"


def test_cli_allow_network_is_the_only_switch_that_reaches_the_fetcher(monkeypatch, capsys):
    calls: list[tuple[str, bool]] = []
    def fetch(url: str, *, context):
        calls.append((url, context.dry_run))
        return _priced_offer(url)
    seen = _spy_on_builder(monkeypatch, fetch)
    assert main(["--candidate-seed", str(SEED), "--allow-network", "--max-candidates", "1", "--max-competitors-per-candidate", "1", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert [item["allow_network"] for item in seen] == [True]
    assert calls == [("https://example-shop.test/products/mini-printer", False)]
    assert report["evidence_mode"] == "public_live" and report["network_used"] is True
    # Public GETs are market context only: still no supplier proof, credential, or live-validated grade.
    assert report["credentials_required"] is False and report["mutated"] is False
    assert report["remaining_supplier_blocker"] == "authenticated_supplier_evidence_not_live_observed"
    synthesis = report["opportunity_synthesis"]
    assert synthesis["overall_recommendation"] == "validate_supplier_first"
    assert synthesis["source_reports"]["supplier"] == "missing"
    assert not synthesis["confidence_grade"].startswith("A_")
