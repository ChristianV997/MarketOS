"""Cross-source evidence safety contracts.

This module is a regression contract, not a runtime provider registry.  The
adapter implementations and the Approval Ledger remain the authorities.  The
matrix below records the externally observable ceiling for the seven source
verticals audited together, while the executable checks exercise mainline
offline boundaries that are already available in this checkout.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import pytest

from backend.adapters.research.market_sources import (
    AdapterFetchError,
    _RealOnlySignalResearchAdapter,
)
from backend.signals.public_signal_policy import public_rss_policy, validate_public_ingestion_request
from evaluation.commerce.consumer_attention import freshness_state, normalize_evidence_mode


EVIDENCE_CLASSES = frozenset(
    {
        "fixture",
        "manual_import",
        "observed",
        "derived",
        "unavailable",
        "blocked",
        "conflicting",
    }
)
NON_LIVE_CLASSES = frozenset({"fixture", "manual_import", "blocked", "unavailable"})
FAILURE_STATUSES = frozenset({"blocked", "error", "missing_credentials", "permission_denied", "empty", "unavailable"})


@dataclass(frozen=True)
class SourceCapability:
    """Test-only declaration of a source's evidence meaning and ceiling."""

    source_id: str
    pr: int
    scope: str
    meaning: str
    default_status: str
    transport_status: str
    requires_account: bool
    prohibited_inferences: frozenset[str]


SOURCE_CAPABILITIES = (
    SourceCapability(
        "ebay_browse",
        479,
        "public_marketplace_listing",
        "public listing, price, shipping, and availability observations",
        "blocked",
        "review_required",
        True,
        frozenset({"supplier_proof", "sales", "launch_authorization"}),
    ),
    SourceCapability(
        "google_trends_interest",
        480,
        "public_market_wide",
        "relative search interest normalized to the selected time and geography",
        "fixture_only",
        "not_documented",
        False,
        frozenset({"absolute_volume", "sales", "supplier_proof", "purchase_intent"}),
    ),
    SourceCapability(
        "meta_ad_library",
        489,
        "public_advertiser_transparency",
        "public ad-library presence and supplied advertiser metadata",
        "fixture_only",
        "review_required",
        True,
        frozenset({"market_demand", "ad_performance", "sales", "launch_authorization"}),
    ),
    SourceCapability(
        "amazon_bestsellers",
        493,
        "public_marketplace_rank",
        "relative bestseller rank when explicitly supplied as offline evidence",
        "unavailable",
        "not_documented",
        True,
        frozenset({"unit_sales", "profit", "supplier_proof", "launch_authorization"}),
    ),
    SourceCapability(
        "tiktok_research",
        494,
        "public_content_research",
        "public research-tool content/account observations where eligibility permits",
        "blocked",
        "not_eligible_for_current_use",
        True,
        frozenset({"market_demand", "supplier_proof", "ad_spend", "launch_authorization"}),
    ),
    SourceCapability(
        "meta_marketing_insights",
        508,
        "authorized_advertiser_account",
        "account-scoped ad delivery and performance metrics",
        "blocked",
        "review_required",
        True,
        frozenset({"market_wide_demand", "competitor_intelligence", "verified_sales", "launch_authorization"}),
    ),
    SourceCapability(
        "google_ads_keyword_planning",
        509,
        "account_scoped_planning",
        "historical keyword-planning metrics for an explicitly targeted geography",
        "blocked",
        "not_implemented",
        True,
        frozenset({"sales", "supplier_proof", "live_campaign_performance", "launch_authorization"}),
    ),
)


def _validate_outcome(capability: SourceCapability, outcome: Mapping[str, Any]) -> None:
    """Validate the observable safety ceiling without normalizing or scoring."""

    required = {
        "status",
        "source_id",
        "evidence_class",
        "provenance",
        "observed_at",
        "geography",
        "language",
        "currency",
        "identity",
        "records",
    }
    missing = required.difference(outcome)
    if missing:
        raise AssertionError(f"outcome missing contract fields: {sorted(missing)}")
    if outcome["evidence_class"] not in EVIDENCE_CLASSES:
        raise AssertionError("unknown evidence class")
    if not isinstance(outcome["source_id"], str) or not outcome["source_id"]:
        raise AssertionError("source identity is required")
    if not isinstance(outcome["identity"], Mapping) or not outcome["identity"].get("workspace_id"):
        raise AssertionError("workspace identity is required")
    if not isinstance(outcome["records"], list):
        raise AssertionError("records must be bounded as a list")
    if outcome["status"] in FAILURE_STATUSES and outcome["records"]:
        raise AssertionError("failure or empty status cannot retain records")
    if outcome["evidence_class"] in NON_LIVE_CLASSES and outcome.get("live_validated"):
        raise AssertionError("offline evidence cannot claim live validation")
    if capability.scope == "authorized_advertiser_account" and outcome.get("market_wide_demand"):
        raise AssertionError("account-scoped evidence cannot claim market-wide demand")
    if outcome.get("raw_payload_stored"):
        raise AssertionError("raw provider payloads cannot cross the evidence contract")
    if outcome.get("credentials_loaded") or outcome.get("network_calls") and outcome.get("status") == "fixture_only":
        raise AssertionError("fixture outcome cannot report credentials or network use")


def _outcome(**overrides: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "fixture_only",
        "source_id": "synthetic-source",
        "evidence_class": "fixture",
        "provenance": "fixture",
        "observed_at": "2026-10-14T00:00:00Z",
        "geography": "US",
        "language": "en",
        "currency": None,
        "identity": {"workspace_id": "workspace-fixture", "account_scope": "synthetic-account"},
        "records": [],
        "live_validated": False,
        "raw_payload_stored": False,
        "credentials_loaded": False,
        "network_calls": False,
    }
    result.update(overrides)
    return result


def test_matrix_covers_all_audited_source_prs_without_authorizing_live_access() -> None:
    assert {item.pr for item in SOURCE_CAPABILITIES} == {479, 480, 489, 493, 494, 508, 509}
    assert len({item.source_id for item in SOURCE_CAPABILITIES}) == len(SOURCE_CAPABILITIES)
    assert all(item.default_status != "live" for item in SOURCE_CAPABILITIES)
    assert all(item.transport_status != "enabled" for item in SOURCE_CAPABILITIES)
    assert all(item.prohibited_inferences for item in SOURCE_CAPABILITIES)


@pytest.mark.parametrize("capability", SOURCE_CAPABILITIES, ids=lambda item: item.source_id)
def test_fixture_manual_and_blocked_results_have_a_hard_non_live_ceiling(capability: SourceCapability) -> None:
    for evidence_class in ("fixture", "manual_import", "blocked", "unavailable"):
        _validate_outcome(
            capability,
            _outcome(evidence_class=evidence_class, provenance=evidence_class),
        )


@pytest.mark.parametrize("status", sorted(FAILURE_STATUSES))
def test_each_failure_status_is_empty_and_unavailable(status: str) -> None:
    capability = SOURCE_CAPABILITIES[0]
    _validate_outcome(
        capability,
        _outcome(status=status, evidence_class="unavailable", provenance="unavailable"),
    )


def test_account_scoped_signals_cannot_be_recast_as_market_demand() -> None:
    capability = next(item for item in SOURCE_CAPABILITIES if item.source_id == "meta_marketing_insights")
    with pytest.raises(AssertionError, match="market-wide demand"):
        _validate_outcome(capability, _outcome(market_wide_demand=True))


def test_live_failure_cannot_fall_back_to_fixture_records() -> None:
    capability = next(item for item in SOURCE_CAPABILITIES if item.source_id == "ebay_browse")
    with pytest.raises(AssertionError, match="failure or empty status"):
        _validate_outcome(
            capability,
            _outcome(status="error", evidence_class="unavailable", provenance="unavailable", records=[{"id": "fixture"}]),
        )


def test_current_signal_boundary_rejects_synthetic_fallback_as_live_rows() -> None:
    class FixtureOnlyAdapter(_RealOnlySignalResearchAdapter):
        name = "synthetic_source"
        synthetic_sources = frozenset({"fixture"})
        confidence_env = "MARKETOS_TEST_CONFIDENCE_BASELINE"
        fetcher = staticmethod(lambda: [{"source": "fixture", "product": "synthetic"}])

    with pytest.raises(AdapterFetchError, match="synthetic fallback"):
        FixtureOnlyAdapter().fetch()


def test_public_signal_policy_requires_explicit_network_opt_in() -> None:
    blocked = validate_public_ingestion_request(
        "rss", "synthetic query", 5, allow_network=False, fixture_mode=False
    )
    assert not blocked.allowed
    assert "network_opt_in_required" in blocked.reasons
    policy = public_rss_policy()
    assert policy.requires_explicit_network_opt_in
    assert "credentialed_fetch" in policy.forbidden_actions


def test_attention_normalization_rejects_untrusted_live_labels_and_preserves_time_states() -> None:
    assert normalize_evidence_mode("live") == "unavailable"
    assert normalize_evidence_mode("fixture") == "fixture"
    assert freshness_state("2027-01-01T00:00:00Z", as_of="2026-10-14T00:00:00Z") == "future_dated"
    assert freshness_state("2020-01-01T00:00:00Z", as_of="2026-10-14T00:00:00Z") == "stale"


@pytest.mark.parametrize("unsafe", ("raw_payload_stored", "credentials_loaded"))
def test_forbidden_transport_or_storage_flags_fail_closed(unsafe: str) -> None:
    capability = SOURCE_CAPABILITIES[0]
    with pytest.raises(AssertionError):
        _validate_outcome(capability, _outcome(**{unsafe: True}))
