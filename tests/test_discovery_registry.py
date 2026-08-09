from backend.discovery.discovery_registry import DiscoveryRegistry as EvidenceDiscoveryRegistry
from backend.discovery.evidence_source_contract import EvidenceRecord
from backend.discovery.registry import DiscoveryRegistry


def test_evidence_registry_missing_and_corrupt_are_empty(tmp_path):
    registry = EvidenceDiscoveryRegistry(tmp_path / "missing.json")
    assert registry.list_evidence() == []
    path = tmp_path / "corrupt.json"
    path.write_text("{broken", encoding="utf-8")
    assert EvidenceDiscoveryRegistry(path).list_evidence() == []


def test_evidence_registry_filters_evidence(tmp_path):
    registry = EvidenceDiscoveryRegistry(tmp_path / "state.json")
    record = EvidenceRecord("e", "local", "fixture", "category", "home", "trend_proxy", .5, 1, .5, 1, {"type": "test"})
    registry.register_evidence([record])
    assert registry.list_evidence(entity_type="category")[0].evidence_id == "e"


def test_register_defaults_to_not_registered_until_first_fetch():
    registry = DiscoveryRegistry()
    registry.register("test_source", credential_env_vars=["FOO_KEY"], requires_auth=True)
    report = registry.status_report()
    assert report[0]["status"] == "not_registered"


def test_record_fetch_success_and_error_are_tracked():
    registry = DiscoveryRegistry()
    registry.register("test_source")
    registry.record_fetch("test_source", count=12)
    assert registry.status_report()[0]["status"] == "live"
    registry.record_fetch("test_source", count=0, error="network timeout")
    assert registry.status_report()[0]["status"] == "error"


def test_zero_count_and_mock_sources_are_not_live(monkeypatch):
    import backend.discovery.registry as registry_mod
    monkeypatch.setattr(registry_mod, "_MOCK_ONLY_SOURCES", {"permanently_mocked_source"})
    registry = DiscoveryRegistry()
    registry.register("permanently_mocked_source")
    registry.record_fetch("permanently_mocked_source", count=5)
    assert registry.status_report()[0]["status"] == "mock_only"
    registry.record_fetch("permanently_mocked_source", count=0)
    assert registry.status_report()[0]["status"] == "mock_fallback"


def test_registry_sorting_and_reregister_history():
    registry = DiscoveryRegistry()
    registry.register("zeta")
    registry.register("alpha")
    assert [item["name"] for item in registry.status_report()] == ["alpha", "zeta"]
    registry.record_fetch("alpha", count=7)
    registry.register("alpha", credential_env_vars=["NEW_KEY"], requires_auth=True)
    assert registry.status_report()[0]["last_fetch_count"] == 7
    assert registry.status_report()[0]["credential_env_vars"] == ["NEW_KEY"]


def test_unregistered_fetch_and_signal_engine_registration():
    registry = DiscoveryRegistry()
    registry.record_fetch("unregistered_source", count=3)
    assert registry.status_report()[0]["status"] == "live"
    import core.signals  # noqa: F401
    from backend.discovery.registry import discovery_registry
    assert {"amazon_bestsellers", "google_trends", "reddit"}.issubset({item["name"] for item in discovery_registry.status_report()})
