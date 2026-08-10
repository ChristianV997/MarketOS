"""Tests for the attempt_competition_evidence opt-in wired into
backend.mvp_commerce.public_run.run_commerce_mvp_from_public_rss."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from backend.adapters.research import competition_evidence as ce_mod
from backend.events.repository import InMemoryEventRepository
from backend.mvp_commerce.public_run import run_commerce_mvp_from_public_rss

ROOT = Path(__file__).resolve().parents[2]
RSS = (ROOT / "tests/fixtures/commerce_mvp_public_network/google_news_rss_success.xml").read_text(encoding="utf-8")

COMPETITOR_HTML = """<html><head><script type="application/ld+json">
{"@type": "Product", "name": "Portable Espresso Maker", "brand": {"name": "Acme"},
 "offers": {"price": "32.00", "priceCurrency": "USD", "availability": "InStock"}}
</script></head></html>"""


class TestCompetitionEvidenceOptIn:
    def test_default_run_never_attempts_competition_evidence(self, tmp_path):
        result = run_commerce_mvp_from_public_rss(query="portable espresso maker", allow_network=True, cache_dir=tmp_path, fetcher=lambda _url, _timeout: RSS)
        types = {event.event_type for event in result.events}
        assert "competition_summary_created" not in types
        assert "market_opportunity_report" not in result.run.metadata

    def test_competition_evidence_without_ranking_gathers_but_does_not_score(self, tmp_path):
        # attempt_competition_evidence only takes effect together with
        # use_opportunity_ranking=True (documented in the function's own
        # docstring) -- without ranking, no scoring/events surface it even
        # if the flag is set.
        with patch.object(ce_mod, "_check_robots", return_value=None), patch.object(ce_mod, "_bounded_get", return_value=COMPETITOR_HTML):
            result = run_commerce_mvp_from_public_rss(
                query="portable espresso maker", allow_network=True, cache_dir=tmp_path, fetcher=lambda _url, _timeout: RSS,
                attempt_competition_evidence=True, competitor_urls=["https://example.com/p"],
            )
        types = {event.event_type for event in result.events}
        assert "competition_summary_created" not in types

    def test_competition_evidence_with_ranking_emits_full_pipeline(self, tmp_path):
        repo = InMemoryEventRepository()
        with patch.object(ce_mod, "_check_robots", return_value=None), patch.object(ce_mod, "_bounded_get", return_value=COMPETITOR_HTML):
            result = run_commerce_mvp_from_public_rss(
                query="portable espresso maker", allow_network=True, cache_dir=tmp_path, fetcher=lambda _url, _timeout: RSS,
                attempt_competition_evidence=True, competitor_urls=["https://example.com/p"],
                use_opportunity_ranking=True, event_repository=repo,
            )
        assert result.status == "succeeded"
        types = {event.event_type for event in result.events}
        assert {"competition_observed", "competition_summary_created", "market_pricing_computed",
                "market_intelligence_completed", "opportunity_scoring_started", "candidate_scored"} <= types
        assert "market_opportunity_report" in result.run.metadata
        assert len(repo.tail()) == len(result.events)

    def test_dry_run_evidence_never_performs_network_io(self, tmp_path):
        # allow_network=False keeps the RSS fetch itself simulated too, so
        # this exercises the same dry-run gate competition evidence shares
        # with supplier evidence.
        with patch.object(ce_mod, "_bounded_get", side_effect=AssertionError("must not fetch competitor pages")):
            result = run_commerce_mvp_from_public_rss(
                query="portable espresso maker", cache_dir=tmp_path,
                attempt_competition_evidence=True, competitor_urls=["https://example.com/p"], use_opportunity_ranking=True,
            )
        assert result.status == "blocked"

    def test_no_competitor_urls_degrades_honestly(self, tmp_path):
        # No competitor_urls supplied -> gather_market_intelligence() finds
        # zero offers; the resulting report must honestly flag
        # "competitor_evidence" as missing rather than silently omitting
        # the report or fabricating pricing.
        with patch.object(ce_mod, "_check_robots", return_value=None):
            result = run_commerce_mvp_from_public_rss(
                query="portable espresso maker", allow_network=True, cache_dir=tmp_path, fetcher=lambda _url, _timeout: RSS,
                attempt_competition_evidence=True, use_opportunity_ranking=True,
            )
        report = result.run.metadata["market_opportunity_report"]
        assert "competitor_evidence" in report["missing_evidence"]
        assert report["observed_pricing"]["median"] is None
