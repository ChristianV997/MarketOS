from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import api.routes.phase1_public_market_benchmark as route
from api.routes.phase1_public_market_benchmark import public_market_benchmark
from backend.adapters.research import competition_evidence
from backend.security.rate_limit import reset_rate_limits_for_tests
from evaluation.commerce.public_market_benchmark import build_public_market_benchmark, load_public_market_seed

PATH = "/api/phase1/public-market-benchmark"
ENV = "MARKETOS_PHASE1_PUBLIC_MARKET_BENCHMARK_REPORT"
ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "tests" / "fixtures" / "public_market_benchmark" / "candidates.json"
CANARIES = ("canaryuser", "canarysecretpw", "querycanary", "fragcanary")
USERINFO_URL = "https://canaryuser:canarysecretpw@public.example/p/widget?tok=querycanary#fragcanary"


def test_public_market_endpoint_returns_read_only_fixture_fallback():
    value = public_market_benchmark()
    assert value["read_only"] is True
    assert value["mutated"] is False
    assert value["network_used"] is False
    assert value["evidence_mode"] == "fixture_demo"
    assert value["marketplace_trend_report"]["candidate_count"] >= 1
    assert value["opportunity_synthesis"]["overall_recommendation"] == "validate_supplier_first"
    assert value["opportunity_synthesis"]["source_reports"]["supplier"] == "missing"


def test_public_market_endpoint_does_not_accept_browser_paths():
    # The GET handler has no path parameter; only a server-side env path can be read.
    assert "competitor_pages_attempted" in public_market_benchmark()


# Mounted HTTP coverage: the cases above call the handler directly and so skip routing, method handling,
# query parsing, response serialization, and the silent ImportError guard around router inclusion.


@pytest.fixture
def artifacts_root(tmp_path: Path, monkeypatch) -> Path:
    root = (tmp_path / "artifacts").resolve()
    root.mkdir()
    monkeypatch.setattr(route, "ARTIFACTS", root)
    return root


@pytest.fixture
def client(monkeypatch):
    """The real backend app over HTTP, without lifespan (no runtime services), with the network tripwired.

    The route is operator-only, so the client carries a synthetic verified operator through the identity overrides.
    """
    from fastapi.testclient import TestClient

    from backend.api import app

    def tripwire(*args, **kwargs):
        raise AssertionError("the public-market route attempted a network fetch")

    monkeypatch.delenv(ENV, raising=False)
    monkeypatch.setattr(competition_evidence, "_validate_public_url", tripwire)
    monkeypatch.setattr(competition_evidence, "_bounded_get", tripwire)
    for dependency, provider in _operator_overrides().items():
        monkeypatch.setitem(app.dependency_overrides, dependency, provider)
    reset_rate_limits_for_tests()
    yield TestClient(app, headers={"Authorization": "Bearer tok-operator"})
    reset_rate_limits_for_tests()


def _operator_overrides() -> dict:
    from backend.identity.errors import IdentityError
    from backend.identity.http import get_token_verifier, get_workspace_repository
    from backend.identity.principal import VerifiedPrincipal
    from backend.identity.roles import INTERNAL_OPERATOR
    from backend.identity.workspaces import WorkspaceAccess

    issuer = "https://clerk.test"

    class Verifier:
        def verify(self, token):
            if token != "tok-operator":
                raise IdentityError()
            return VerifiedPrincipal(issuer, "user_operator")

    class Repository:
        def memberships_for(self, principal):
            return [WorkspaceAccess(issuer, principal.subject, "ws_phase1_synthetic", "internal", "synthetic", INTERNAL_OPERATOR)]

    return {get_token_verifier: Verifier, get_workspace_repository: Repository}


def _stored_report() -> dict:
    candidates, _ = load_public_market_seed(SEED)
    return build_public_market_benchmark(candidates, max_candidates=2).to_dict()


def _configure(monkeypatch, path: Path, report: dict) -> None:
    path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setenv(ENV, str(path))


def test_route_is_mounted_and_serves_the_fixture_fallback_over_http(client):
    response = client.get(PATH)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["read_only"] is True and body["mutated"] is False and body["credentials_required"] is False
    assert body["network_used"] is False and body["evidence_mode"] == "fixture_demo"
    assert {"server_artifact_not_configured_using_fixture_demo", "fixture_demo_evidence_only_not_live_proof"} <= set(body["warnings"])
    assert body["remaining_supplier_blocker"] == "authenticated_supplier_evidence_not_live_observed"
    assert body["marketplace_trend_report"]["network_calls"] is False
    assert body["opportunity_synthesis"]["overall_recommendation"] == "validate_supplier_first"
    assert body["opportunity_synthesis"]["source_reports"]["supplier"] == "missing"


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_route_is_get_only_over_http(client, method: str):
    response = getattr(client, method)(PATH)
    assert response.status_code == 405


def test_route_ignores_browser_supplied_paths_flags_and_urls(client):
    plain = client.get(PATH).json()
    probed = client.get(
        PATH,
        params={"path": "/etc/passwd", "report": "../../outside.json", "allow_network": "true", "url": "https://public.example/x"},
    )
    assert probed.status_code == 200
    body = probed.json()
    assert body["network_used"] is False and body["evidence_mode"] == "fixture_demo"
    assert body["candidate_results"] == plain["candidate_results"]


def test_route_serves_a_server_configured_artifact_under_artifacts(client, monkeypatch, artifacts_root):
    report = _stored_report()
    report["warnings"] = [*report["warnings"], "configured_artifact_marker"]
    _configure(monkeypatch, artifacts_root / "public_market.json", report)
    body = client.get(PATH).json()
    assert "configured_artifact_marker" in body["warnings"]
    assert "server_artifact_not_configured_using_fixture_demo" not in body["warnings"]
    assert body["read_only"] is True and body["mutated"] is False
    assert body["marketplace_trend_report"]["candidate_count"] >= 1
    assert body["opportunity_synthesis"]["source_reports"]["supplier"] == "missing"


def test_route_ignores_a_configured_artifact_outside_artifacts(client, monkeypatch, tmp_path, artifacts_root):
    report = _stored_report()
    report["warnings"] = [*report["warnings"], "outside_artifact_marker"]
    outside = tmp_path / "outside.json"
    _configure(monkeypatch, outside, report)
    body = client.get(PATH).json()
    assert "outside_artifact_marker" not in body["warnings"]
    assert "server_artifact_not_configured_using_fixture_demo" in body["warnings"]


def test_route_strips_url_userinfo_and_query_from_stored_artifacts(client, monkeypatch, artifacts_root):
    # An artifact written before URL sanitization covered userinfo must still not be echoed back.
    report = _stored_report()
    evidence = report["candidate_results"][0]["evidence"][0]
    evidence["competitor_url"] = USERINFO_URL
    evidence["warnings"] = [f"robots_blocked:robots.txt disallows evidence URL: {USERINFO_URL}"]
    report["marketplace_trend_report"] = {"candidates": [{"evidence": [{"source_url": USERINFO_URL}]}], "candidate_count": 1}
    _configure(monkeypatch, artifacts_root / "legacy.json", report)
    response = client.get(PATH)
    assert response.status_code == 200
    assert [name for name in CANARIES if name in response.text] == []
    assert response.json()["candidate_results"][0]["evidence"][0]["competitor_url"] == "https://public.example/p/widget"


def test_route_degrades_instead_of_failing_on_a_malformed_stored_artifact(client, monkeypatch, artifacts_root):
    report = _stored_report()
    report["candidate_results"] = [{"candidate_id": "c1", "evidence": [{"price": 5.0, "product_title": "T", "field_provenance": "not-a-mapping"}]}]
    _configure(monkeypatch, artifacts_root / "malformed.json", report)
    response = client.get(PATH)
    assert response.status_code == 200
    body = response.json()
    assert "canonical_projection_unavailable" in body["warnings"]
    assert body["read_only"] is True and body["mutated"] is False


def test_route_redacts_credential_shaped_keys_in_stored_artifacts(client, monkeypatch, artifacts_root):
    report = _stored_report()
    report["api_key"] = "synthetic-key-value"
    _configure(monkeypatch, artifacts_root / "keys.json", report)
    response = client.get(PATH)
    assert response.status_code == 200
    assert "synthetic-key-value" not in response.text


def test_route_rate_limit_is_a_read_only_429_over_http(client, monkeypatch):
    monkeypatch.setattr("api.routes.event_access.check_rate_limit", lambda *args, **kwargs: SimpleNamespace(allowed=False, retry_after_seconds=5))
    response = client.get(PATH)
    assert response.status_code == 429
    body = response.json()["detail"]
    assert body["status"] == "rate_limited" and body["read_only"] is True and body["mutated"] is False


SECRET_PATH_TOKEN = "sk-" + "SYNTHETICEXAMPLE0123456789"


def test_route_replaces_secret_shaped_url_paths_in_stored_artifacts(client, monkeypatch, artifacts_root):
    report = _stored_report()
    evidence = report["candidate_results"][0]["evidence"][0]
    evidence["competitor_url"] = f"https://public.example/api/{SECRET_PATH_TOKEN}/widget"
    report["marketplace_trend_report"] = {"candidates": [{"evidence": [{"source_url": f"https://public.example/{SECRET_PATH_TOKEN}"}]}], "candidate_count": 1}
    _configure(monkeypatch, artifacts_root / "secret_path.json", report)
    response = client.get(PATH)
    assert response.status_code == 200
    assert "SYNTHETIC" not in response.text
    assert response.json()["candidate_results"][0]["evidence"][0]["competitor_url"] == "https://public.example/api/[redacted]/widget"


def test_route_keeps_benign_slugs_in_stored_artifacts(client, monkeypatch, artifacts_root):
    report = _stored_report()
    report["candidate_results"][0]["evidence"][0]["competitor_url"] = "https://public.example/products/desk-clamp-lamp"
    _configure(monkeypatch, artifacts_root / "benign.json", report)
    assert client.get(PATH).json()["candidate_results"][0]["evidence"][0]["competitor_url"] == "https://public.example/products/desk-clamp-lamp"


def test_route_returns_an_artifact_without_candidate_results_unprojected(client, monkeypatch, artifacts_root):
    _configure(monkeypatch, artifacts_root / "bare.json", {"evidence_mode": "fixture_demo", "warnings": ["bare_artifact_marker"]})
    response = client.get(PATH)
    assert response.status_code == 200
    body = response.json()
    assert "bare_artifact_marker" in body["warnings"]
    assert "marketplace_trend_report" not in body and "opportunity_synthesis" not in body
    assert body["read_only"] is True and body["mutated"] is False


def test_route_rejects_a_symlinked_artifact_that_leaves_artifacts(client, monkeypatch, tmp_path, artifacts_root):
    outside = tmp_path / "outside.json"
    report = _stored_report()
    report["warnings"] = [*report["warnings"], "outside_symlink_marker"]
    outside.write_text(json.dumps(report), encoding="utf-8")
    link = artifacts_root / "link.json"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"NOT COVERED: symlinks unavailable on this host ({type(exc).__name__})")
    monkeypatch.setenv(ENV, str(link))
    body = client.get(PATH).json()
    assert "outside_symlink_marker" not in body["warnings"]
    assert "server_artifact_not_configured_using_fixture_demo" in body["warnings"]


def test_route_enforces_the_real_rate_limit_over_http(client, monkeypatch):
    monkeypatch.setenv("MARKETOS_EVENT_READ_RATE_LIMIT", "2")
    reset_rate_limits_for_tests()
    assert [client.get(PATH).status_code for _ in range(2)] == [200, 200]
    limited = client.get(PATH)
    assert limited.status_code == 429
    body = limited.json()["detail"]
    assert body["status"] == "rate_limited" and body["read_only"] is True and body["mutated"] is False


def test_public_market_route_refuses_anonymous_reads(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.api import app

    for dependency, provider in _operator_overrides().items():
        monkeypatch.setitem(app.dependency_overrides, dependency, provider)
    response = TestClient(app).get("/api/phase1/public-market-benchmark")

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "missing_credentials"}}
