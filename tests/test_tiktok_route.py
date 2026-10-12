"""Route-level safety tests for the mounted TikTok API surface."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api.routes.tiktok import router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _raise_sensitive_error(*args, **kwargs):
    raise RuntimeError("token=synthetic-secret C:\\private\\provider\\traceback")


def _install_playbook(monkeypatch) -> None:
    from core.content.playbook import Playbook, playbook_memory

    playbook = Playbook(
        product="synthetic-product",
        phase="EXPLORE",
        top_hooks=["synthetic hook"],
        top_angles=["synthetic angle"],
        estimated_roas=1.0,
        confidence=0.5,
        evidence_count=1,
    )
    monkeypatch.setattr(playbook_memory, "get", lambda _product: playbook)


def test_launch_blocks_live_action_even_with_caller_approval_claims(client, monkeypatch):
    from backend.integrations import tiktok_ads
    from evaluation.companyos import approval_ledger

    monkeypatch.setattr(tiktok_ads, "_DRY_RUN", False)
    actions = []
    simulate_action = approval_ledger.simulate_action

    def record_simulation(action: str):
        actions.append(action)
        return simulate_action(action)

    monkeypatch.setattr(approval_ledger, "simulate_action", record_simulation)
    monkeypatch.setattr(tiktok_ads, "launch_from_playbook", _raise_sensitive_error)

    response = client.post(
        "/tiktok/launch?product=synthetic-product&approved=true"
        "&approval_id=caller-approval&workspace_id=caller-workspace"
    )

    assert response.status_code == 403
    assert response.json()["status"] == "blocked"
    assert response.json()["error"] == "live_action_not_approved"
    assert response.json()["approval_status"] == "would_be_blocked_by_policy"
    assert actions == ["launch_ad"]


def test_check_blocks_live_mutation_even_with_caller_approval_claims(client, monkeypatch):
    from backend.integrations import tiktok_ads
    from evaluation.companyos import approval_ledger

    monkeypatch.setattr(tiktok_ads, "_DRY_RUN", False)
    actions = []
    simulate_action = approval_ledger.simulate_action

    def record_simulation(action: str):
        actions.append(action)
        return simulate_action(action)

    monkeypatch.setattr(approval_ledger, "simulate_action", record_simulation)
    monkeypatch.setattr(tiktok_ads, "check_and_act", _raise_sensitive_error)

    response = client.post(
        "/tiktok/check?campaign_id=caller-campaign&spend=150&budget=100&roas=0.1"
        "&approved=true&approval_id=caller-approval"
    )

    assert response.status_code == 403
    assert response.json()["status"] == "blocked"
    assert response.json()["error"] == "live_action_not_approved"
    assert response.json()["approval_status"] == "would_be_blocked_by_policy"
    assert actions == ["launch_ad"]


def test_roas_report_blocks_live_provider_call_and_preserves_report_shape(client, monkeypatch):
    from backend.integrations import tiktok_ads
    from evaluation.companyos import approval_ledger

    monkeypatch.setattr(tiktok_ads, "_DRY_RUN", False)
    actions = []
    simulate_action = approval_ledger.simulate_action

    def record_simulation(action: str):
        actions.append(action)
        return simulate_action(action)

    monkeypatch.setattr(approval_ledger, "simulate_action", record_simulation)
    monkeypatch.setattr(tiktok_ads, "fetch_roas", _raise_sensitive_error)

    response = client.get("/tiktok/roas?approved=true&approval_id=caller-approval")

    assert response.status_code == 403
    assert response.json() == {
        "status": "blocked",
        "error": "provider_call_not_approved",
        "approval_status": "would_be_blocked_by_policy",
        "roas": {},
        "campaign_count": 0,
    }
    assert actions == ["provider_call"]


def test_live_action_fails_closed_if_approval_policy_is_unavailable(client, monkeypatch):
    from backend.integrations import tiktok_ads
    from evaluation.companyos import approval_ledger

    monkeypatch.setattr(tiktok_ads, "_DRY_RUN", False)
    monkeypatch.setattr(approval_ledger, "simulate_action", _raise_sensitive_error)
    monkeypatch.setattr(tiktok_ads, "launch_from_playbook", _raise_sensitive_error)

    response = client.post("/tiktok/launch?product=synthetic-product&approved=true")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "error": "approval_policy_unavailable",
    }
    assert "synthetic-secret" not in response.text
    assert "C:\\private" not in response.text


def test_dry_run_launch_remains_simulated_and_compatible(client, monkeypatch):
    from backend.integrations import tiktok_ads

    monkeypatch.setattr(tiktok_ads, "_DRY_RUN", True)
    _install_playbook(monkeypatch)

    response = client.post("/tiktok/launch?product=synthetic-product&phase=EXPLORE")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["dry_run"] is True
    assert payload["campaign_id"].startswith("dry_")
    assert payload["adgroup_id"].startswith("dry_")
    assert payload["ad_ids"]


def test_dry_run_check_is_explicit_and_does_not_call_provider(client, monkeypatch):
    from backend.integrations import tiktok_ads

    monkeypatch.setattr(tiktok_ads, "_DRY_RUN", True)
    monkeypatch.setattr(tiktok_ads, "_roas_streaks", {})
    post_calls = []
    original_post = tiktok_ads._post

    def dry_run_post(path, payload):
        post_calls.append((path, payload))
        return original_post(path, payload)

    monkeypatch.setattr(tiktok_ads, "_post", dry_run_post)

    response = client.post(
        "/tiktok/check?campaign_id=synthetic-campaign&spend=130&budget=100&roas=0.5"
    )

    assert response.status_code == 200
    assert response.json() == {
        "campaign_id": "synthetic-campaign",
        "action": "killed",
        "dry_run": True,
    }
    assert post_calls == [
        (
            "/campaign/status/update/",
            {
                "advertiser_id": "",
                "campaign_ids": ["synthetic-campaign"],
                "opt_status": "DISABLE",
            },
        )
    ]


def test_dry_run_roas_report_keeps_existing_keys_and_marks_simulation(
    client, monkeypatch
):
    from backend.integrations import tiktok_ads

    monkeypatch.setattr(tiktok_ads, "_DRY_RUN", True)
    monkeypatch.setattr(
        tiktok_ads,
        "_get",
        lambda *_args, **_kwargs: pytest.fail("dry-run reporting must not call provider"),
    )

    response = client.get("/tiktok/roas")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) >= {"roas", "campaign_count", "dry_run"}
    assert payload["dry_run"] is True
    assert isinstance(payload["roas"], dict)
    assert payload["campaign_count"] == len(payload["roas"])


@pytest.mark.parametrize(
    ("path", "patch_name", "setup_playbook", "expected_error"),
    [
        (
            "/tiktok/launch?product=synthetic-product",
            "launch_from_playbook",
            True,
            "launch_unavailable",
        ),
        ("/tiktok/roas", "fetch_roas", False, "reporting_unavailable"),
        (
            "/tiktok/check?campaign_id=synthetic&spend=20&budget=100&roas=1.0",
            "check_and_act",
            False,
            "check_unavailable",
        ),
    ],
)
def test_route_exceptions_do_not_expose_secrets_or_paths(
    client, monkeypatch, path, patch_name, setup_playbook, expected_error
):
    from backend.integrations import tiktok_ads

    monkeypatch.setattr(tiktok_ads, "_DRY_RUN", True)
    monkeypatch.setattr(tiktok_ads, patch_name, _raise_sensitive_error)
    if setup_playbook:
        _install_playbook(monkeypatch)

    method = client.get if path.startswith("/tiktok/roas") else client.post
    response = method(path)

    assert response.status_code == 503
    assert response.json()["error"] == expected_error
    assert "synthetic-secret" not in response.text
    assert "C:\\private" not in response.text
    assert "traceback" not in response.text.lower()
