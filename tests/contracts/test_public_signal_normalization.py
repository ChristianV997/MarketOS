import json
from pathlib import Path

from backend.signals.public_sources import RSS_SOURCE, build_rss_url, normalize_rss_xml


ROOT = Path("tests/fixtures/public_signals")


def test_rss_normalization_is_deterministic_and_handles_partial_duplicate_records():
    xml = (ROOT / "rss_sample.xml").read_text(encoding="utf-8")
    url = build_rss_url("ecommerce trends")
    first, warnings = normalize_rss_xml(xml, "ecommerce trends", source_url=url, limit=10)
    second, second_warnings = normalize_rss_xml(xml, "ecommerce trends", source_url=url, limit=10)
    expected = json.loads((ROOT / "normalized_signals.expected.json").read_text())
    assert [item.to_dict() for item in first] == [item.to_dict() for item in second]
    assert warnings == second_warnings == ["deduplicated_item", "skipped_partial_item"]
    assert [(item.title, item.rank, item.score, item.attribution["publisher"], item.observed_at) for item in first] == [
        (item["title"], item["rank"], item["score"], item["publisher"], item["observed_at"]) for item in expected
    ]
    assert all(item.source == RSS_SOURCE and item.dry_run and item.advisory for item in first)


def test_invalid_xml_returns_a_clear_non_crashing_warning():
    signals, warnings = normalize_rss_xml("<rss>", "topic", source_url="https://example.test")
    assert signals == []
    assert warnings == ["invalid_rss_xml"]
