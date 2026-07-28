"""Tests for backend.discovery.registry — central discovery-source health tracking."""
from backend.discovery.registry import DiscoveryRegistry


def test_register_defaults_to_not_registered_until_first_fetch():
    registry = DiscoveryRegistry()
    registry.register("test_source", credential_env_vars=["FOO_KEY"], requires_auth=True)
    report = registry.status_report()
    assert len(report) == 1
    assert report[0]["name"] == "test_source"
    assert report[0]["status"] == "not_registered"
    assert report[0]["credential_env_vars"] == ["FOO_KEY"]
    assert report[0]["requires_auth"] is True


def test_record_fetch_success_marks_live():
    registry = DiscoveryRegistry()
    registry.register("test_source")
    registry.record_fetch("test_source", count=12)
    report = registry.status_report()
    assert report[0]["status"] == "live"
    assert report[0]["last_fetch_count"] == 12
    assert report[0]["last_error"] is None


def test_record_fetch_error_marks_error():
    registry = DiscoveryRegistry()
    registry.register("test_source")
    registry.record_fetch("test_source", count=0, error="network timeout")
    report = registry.status_report()
    assert report[0]["status"] == "error"
    assert report[0]["last_error"] == "network timeout"


def test_record_fetch_zero_count_no_error_is_mock_fallback():
    registry = DiscoveryRegistry()
    registry.register("test_source")
    registry.record_fetch("test_source", count=0)
    report = registry.status_report()
    assert report[0]["status"] == "mock_fallback"


def test_known_mock_only_source_never_reports_live(monkeypatch):
    import backend.discovery.registry as registry_mod
    monkeypatch.setattr(registry_mod, "_MOCK_ONLY_SOURCES", {"permanently_mocked_source"})

    registry = DiscoveryRegistry()
    registry.register("permanently_mocked_source")
    registry.record_fetch("permanently_mocked_source", count=5)  # nonzero, but it's all mock data
    report = registry.status_report()
    assert report[0]["status"] == "mock_only"


def test_known_mock_fallback_source_never_reports_live():
    """alibaba moved from mock_only to mock_fallback once its optional
    Firecrawl-backed real path was added (backend/adapters/alibaba_trends.py)
    — it's conservatively treated the same as every other scraper here
    whose real-data success isn't guaranteed run-to-run, same as before."""
    registry = DiscoveryRegistry()
    registry.register("alibaba")
    registry.record_fetch("alibaba", count=5)  # nonzero count, but it's all mock data
    report = registry.status_report()
    assert report[0]["status"] == "mock_fallback"


def test_record_fetch_without_prior_register_still_tracked():
    registry = DiscoveryRegistry()
    registry.record_fetch("unregistered_source", count=3)
    report = registry.status_report()
    assert any(s["name"] == "unregistered_source" and s["status"] == "live" for s in report)


def test_status_report_sorted_by_name():
    registry = DiscoveryRegistry()
    registry.register("zeta")
    registry.register("alpha")
    report = registry.status_report()
    assert [s["name"] for s in report] == ["alpha", "zeta"]


def test_reregister_preserves_fetch_history():
    registry = DiscoveryRegistry()
    registry.register("test_source", credential_env_vars=[])
    registry.record_fetch("test_source", count=7)
    registry.register("test_source", credential_env_vars=["NEW_KEY"], requires_auth=True)
    report = registry.status_report()
    assert report[0]["last_fetch_count"] == 7  # fetch history untouched
    assert report[0]["credential_env_vars"] == ["NEW_KEY"]  # metadata updated


def test_signal_engine_get_populates_registry_via_import():
    """Smoke test: importing core.signals triggers _register_adapters(), which
    should populate the module-level discovery_registry with every known source."""
    import core.signals  # noqa: F401 — triggers _register_adapters() at import time
    from backend.discovery.registry import discovery_registry

    report = discovery_registry.status_report()
    names = {s["name"] for s in report}
    expected = {"amazon_bestsellers", "tiktok_organic", "google_trends",
                "reddit", "youtube_trends", "mercadolibre", "alibaba"}
    assert expected.issubset(names)
