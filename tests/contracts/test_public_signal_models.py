from backend.signals.public_signal_models import PublicSignal, signal_identifier


def test_public_signal_is_json_safe_bounded_and_advisory():
    signal = PublicSignal(
        signal_id="signal-1", source="rss", source_url="https://example.test/feed", observed_at=1,
        query="topic", title="Observed title", description="description", score=2.0, rank=1,
        metadata={"not_finite": float("inf")},
    )
    assert signal.score == 1.0
    assert signal.dry_run and signal.advisory
    assert signal.to_dict()["metadata"]["not_finite"] is None
    assert PublicSignal.from_dict(signal.to_dict()) == signal


def test_signal_identifier_is_content_derived_and_deterministic():
    first = signal_identifier("rss", "Query", "https://example.test/a", "Title")
    assert first == signal_identifier("rss", " query ", "https://example.test/a", "Title")
    assert first != signal_identifier("rss", "query", "https://example.test/b", "Title")
