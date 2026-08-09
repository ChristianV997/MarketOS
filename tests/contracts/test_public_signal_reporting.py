import json
from pathlib import Path

from backend.contracts.events import Event
from backend.signals.public_signal_reporting import audit_to_json, audit_to_markdown, build_public_signal_audit, validate_public_signal_events
from backend.signals.public_sources import ingest_public_rss, public_signal_event


ROOT = Path("tests/fixtures/public_signals")


def test_public_signal_audit_is_deterministic_and_reports_limits():
    result = ingest_public_rss("ecommerce trends", fixture_xml=(ROOT / "rss_sample.xml").read_text())
    first = build_public_signal_audit(result, workspace_id="fixture-workspace")
    second = build_public_signal_audit(result, workspace_id="fixture-workspace")
    expected = json.loads((ROOT / "public_signal_audit.expected.json").read_text())
    assert audit_to_json(first) == audit_to_json(second)
    for key, value in expected.items():
        assert first.to_dict()[key] == value
    assert "not proof of demand" in audit_to_markdown(first)
    assert "no launch" in audit_to_markdown(first).lower()


def test_public_signal_audit_detects_authority_and_envelope_regressions():
    result = ingest_public_rss("ecommerce trends", fixture_xml=(ROOT / "rss_sample.xml").read_text())
    event = public_signal_event(result.signals[0], "fixture-workspace", cache_status="fixture")
    unsafe = Event.from_dict({**event.to_dict(), "metadata": {**event.metadata, "live_authority": True, "no_spend_authority": False}})
    issues = validate_public_signal_events([unsafe])
    assert any("live_authority" in item for item in issues)
    assert any("no_spend_authority" in item for item in issues)


def test_blocked_ingestion_audit_remains_advisory_and_recommends_safe_next_step():
    result = ingest_public_rss("topic")
    audit = build_public_signal_audit(result)
    assert audit.ingestion_status == "blocked"
    assert audit.event_count == 0
    assert audit.advisory_only is True
    assert "fixtures" in audit.next_actions[0].lower()
