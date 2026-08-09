import json
from pathlib import Path

from backend.signals.public_signal_cache import PublicSignalCache
from backend.signals.public_sources import ingest_public_rss, public_rss_readiness


ROOT = Path("tests/fixtures/public_signals")


def test_fixture_ingestion_matches_report_and_never_uses_network(tmp_path):
    result = ingest_public_rss("ecommerce trends", cache=PublicSignalCache(tmp_path), fixture_xml=(ROOT / "rss_sample.xml").read_text())
    expected = json.loads((ROOT / "ingestion_report.expected.json").read_text())
    assert result.status == expected["status"]
    assert result.cache_status == expected["cache_status"]
    assert len(result.signals) == expected["signal_count"]
    assert result.network_used is expected["network_used"]
    assert result.warnings == expected["warnings"]


def test_network_is_blocked_by_default_and_stale_cache_is_used_deterministically(tmp_path):
    cache = PublicSignalCache(tmp_path)
    blocked = ingest_public_rss("ecommerce trends", cache=cache)
    expected_blocked = json.loads((ROOT / "network_blocked_report.expected.json").read_text())
    assert blocked.status == expected_blocked["status"]
    assert blocked.errors == [expected_blocked["error"]]
    fixture = ingest_public_rss("ecommerce trends", fixture_xml=(ROOT / "rss_sample.xml").read_text())
    cache.save(fixture.source, fixture.query, [item.to_dict() for item in fixture.signals], fixture.source_url, saved_at=123.0)
    stale = ingest_public_rss("ecommerce trends", cache=cache)
    expected_stale = json.loads((ROOT / "stale_cache_report.expected.json").read_text())
    assert stale.status == expected_stale["status"]
    assert stale.cache_status == expected_stale["cache_status"]
    assert stale.network_used is expected_stale["network_used"]
    assert stale.warnings == [expected_stale["warning"]]
    readiness = public_rss_readiness(cache, "ecommerce trends")
    assert readiness["requires_credentials"] is False
    assert readiness["cache_available"] is True
    assert "spend" in readiness["forbidden_actions"]


def test_network_failure_serves_stale_cache_without_raising(tmp_path):
    cache = PublicSignalCache(tmp_path)
    fixture = ingest_public_rss("topic", fixture_xml=(ROOT / "rss_sample.xml").read_text())
    cache.save(fixture.source, fixture.query, [item.to_dict() for item in fixture.signals], fixture.source_url)

    def fail(url, timeout):
        raise OSError("network unavailable")

    result = ingest_public_rss("topic", allow_network=True, cache=cache, fetcher=fail)
    assert result.status == "stale_cache"
    assert result.cache_status == "stale"
    assert result.warnings == ["network_failure:OSError"]


def test_corrupted_cache_does_not_crash_orauthorize_network(tmp_path):
    cache = PublicSignalCache(tmp_path)
    cache.directory.mkdir(parents=True, exist_ok=True)
    cache._path("google_news_rss", "topic").write_text("not-json", encoding="utf-8")
    result = ingest_public_rss("topic", cache=cache)
    assert result.status == "blocked"
    assert result.network_used is False


def test_cache_key_is_query_scoped_and_atomic_payload_is_readable(tmp_path):
    cache = PublicSignalCache(tmp_path)
    fixture = ingest_public_rss("ecommerce trends", fixture_xml=(ROOT / "rss_sample.xml").read_text())
    cache.save(fixture.source, fixture.query, [item.to_dict() for item in fixture.signals], fixture.source_url, saved_at=456.0)
    cached = cache.load(fixture.source, fixture.query)
    assert cached["saved_at"] == 456.0
    assert len(cached["signals"]) == 2
    assert cache.load(fixture.source, "different query") is None
    assert list(tmp_path.glob("*.tmp")) == []
