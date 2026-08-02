"""Readiness and credential-boundary tests for market research staging."""
from __future__ import annotations

from datetime import datetime, timezone

from backend.research.credentials import load_research_credentials
from backend.research.readiness import all_source_readiness, source_readiness


def test_secrets_manager_loader_imports_only_allowlisted_keys(monkeypatch):
    monkeypatch.setenv("MARKETOS_RESEARCH_SECRET_ID", "marketos/staging/research")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.delenv("TIKTOK_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("TIKTOK_ADVERTISER_ID", raising=False)

    class FakeClient:
        def get_secret_value(self, *, SecretId):
            assert SecretId == "marketos/staging/research"
            return {
                "SecretString": (
                    '{"TIKTOK_ACCESS_TOKEN":"token-value",'
                    '"TIKTOK_ADVERTISER_ID":"advertiser-value",'
                    '"UNRELATED_SECRET":"must-not-load"}'
                )
            }

    status = load_research_credentials(force=True, client_factory=lambda: FakeClient())

    assert status.loaded is True
    assert status.loaded_keys == ("TIKTOK_ACCESS_TOKEN", "TIKTOK_ADVERTISER_ID")
    assert status.public_dict()["loaded_keys"] == ["TIKTOK_ACCESS_TOKEN", "TIKTOK_ADVERTISER_ID"]
    assert "token-value" not in str(status.public_dict())
    assert "UNRELATED_SECRET" not in str(status.public_dict())
    assert __import__("os").environ["TIKTOK_ACCESS_TOKEN"] == "token-value"
    assert __import__("os").environ["TIKTOK_ADVERTISER_ID"] == "advertiser-value"


def test_secret_loader_reports_provider_failure_without_secret_values(monkeypatch):
    monkeypatch.setenv("MARKETOS_RESEARCH_SECRET_ID", "marketos/staging/research")

    class BrokenClient:
        def get_secret_value(self, *, SecretId):
            raise RuntimeError("token-value must not escape")

    status = load_research_credentials(force=True, client_factory=lambda: BrokenClient())

    assert status.loaded is False
    assert status.error_type == "RuntimeError"
    assert "token-value" not in str(status.public_dict())


def test_tiktok_readiness_fails_closed_without_required_credentials(monkeypatch):
    monkeypatch.setenv("FF_PILLAR_A_INGESTION", "true")
    monkeypatch.setenv("FF_RESEARCH_SOURCE_TIKTOK_ORGANIC", "true")
    monkeypatch.delenv("TIKTOK_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("TIKTOK_ADVERTISER_ID", raising=False)
    monkeypatch.delenv("MARKETOS_RESEARCH_SECRET_ID", raising=False)

    readiness = source_readiness("tiktok_organic")

    assert readiness["status"] == "missing_credentials"
    assert set(readiness["missing_credentials"]) == {"TIKTOK_ACCESS_TOKEN", "TIKTOK_ADVERTISER_ID"}


def test_all_source_readiness_reports_disabled_sources_and_recent_coverage(monkeypatch):
    monkeypatch.setenv("FF_PILLAR_A_INGESTION", "false")
    monkeypatch.delenv("MARKETOS_RESEARCH_SECRET_ID", raising=False)

    payload = all_source_readiness(
        summaries=[{
            "source": "reddit",
            "record_count": 4,
            "topic_count": 3,
            "confidence": 0.5,
            "freshness_ts": datetime.now(timezone.utc).isoformat(),
        }]
    )

    assert payload["global_ingestion_enabled"] is False
    assert payload["credential_store"]["loaded"] is False
    reddit = next(item for item in payload["sources"] if item["name"] == "reddit")
    assert reddit["status"] == "disabled"
    assert reddit["reason"] == "global_flag_disabled"
    assert reddit["record_count"] == 4
    assert all("token-value" not in str(item) for item in payload["sources"])


def test_source_reliability_requires_three_quality_runs_and_fresh_records():
    from backend.research.readiness import source_reliability

    now = datetime.now(timezone.utc)
    runs = [
        {"payload": {"sources": {"reddit": {"status": "succeeded", "fetched": 8, "rejected": 0}}}},
        {"payload": {"sources": {"reddit": {"status": "succeeded", "fetched": 7, "rejected": 0}}}},
        {"payload": {"sources": {"reddit": {"status": "succeeded", "fetched": 6, "rejected": 0}}}},
    ]

    result = source_reliability(
        "reddit",
        runs=runs,
        summary={"record_count": 8, "freshness_ts": now.isoformat()},
        now=now,
    )

    assert result["reliable"] is True
    assert result["consecutive_successful_runs"] == 3
    assert all(check["rejection_rate_ok"] for check in result["quality_checks"])
