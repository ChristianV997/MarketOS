from pathlib import Path

from backend.events.repository import InMemoryEventRepository
from backend.mvp_commerce.public_run import run_commerce_mvp_from_public_rss

ROOT = Path(__file__).resolve().parents[2]
RSS = (ROOT / "tests/fixtures/commerce_mvp_public_network/google_news_rss_success.xml").read_text(encoding="utf-8")


def test_public_runner_success_emits_signal_and_commerce_events(tmp_path):
    repo = InMemoryEventRepository()
    result = run_commerce_mvp_from_public_rss(query="portable espresso maker", allow_network=True, cache_dir=tmp_path, fetcher=lambda _url, _timeout: RSS, event_repository=repo)
    assert result.status == "succeeded"
    assert len(result.ingestion.signals) == 2
    assert {event.event_type for event in result.events} >= {"public_signal_observed", "commerce_mvp_run_started", "commerce_mvp_run_completed"}
    assert len(repo.tail()) == len(result.events)
    assert result.run.metadata["network_used"] is True
    assert all(event.metadata["non_authoritative"] for event in result.events)


def test_public_runner_blocks_without_network_and_degrades_without_cache(tmp_path):
    blocked = run_commerce_mvp_from_public_rss(query="portable espresso maker", cache_dir=tmp_path)
    assert blocked.status == "blocked"
    assert blocked.ingestion.network_used is False

    degraded = run_commerce_mvp_from_public_rss(query="portable espresso maker", allow_network=True, cache_dir=tmp_path, fetcher=lambda _url, _timeout: (_ for _ in ()).throw(TimeoutError("offline")))
    assert degraded.status == "degraded"
    assert degraded.ingestion.network_used is True
    assert degraded.ingestion.signals == []


def test_public_runner_uses_stale_cache_after_network_failure(tmp_path):
    run_commerce_mvp_from_public_rss(query="portable espresso maker", allow_network=True, cache_dir=tmp_path, fetcher=lambda _url, _timeout: RSS)
    stale = run_commerce_mvp_from_public_rss(query="portable espresso maker", allow_network=True, cache_dir=tmp_path, fetcher=lambda _url, _timeout: (_ for _ in ()).throw(TimeoutError("offline")))
    assert stale.status == "stale_cache"
    assert stale.ingestion.cache_status == "stale"
    assert len(stale.ingestion.signals) == 2
