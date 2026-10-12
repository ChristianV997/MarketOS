import json
import threading

import pytest

import backend.discovery.refinement_registry as refinement_module
from backend.discovery.evidence_gap import EvidenceGapAnalysis
from backend.discovery.import_recommendation import ImportRecommendationPlan
from backend.discovery.import_templates import ImportTemplate
from backend.discovery.refinement_registry import RefinementRegistry, RegistryPersistenceError

VALID_GAP = EvidenceGapAnalysis("a", "w", "t", "o").to_dict()
INVALID_STATE_CASES = [
    ("top_level_list", []),
    ("section_not_object", {"gap_analyses": []}),
    ("record_not_object", {"gap_analyses": {"a": "text"}}),
    ("record_missing_fields", {"gap_analyses": {"a": {"analysis_id": "a"}}}),
    ("key_differs_from_identity", {"gap_analyses": {"other": VALID_GAP}}),
]


def _gap(item_id="a"):
    return EvidenceGapAnalysis(item_id, "w", "t", "o")


def _template():
    return ImportTemplate("t", "generic_market_csv", "t", "d", [], [], [], "data/import_templates/generic_market_csv.csv")


def _temp_leftovers(directory):
    return [item.name for item in directory.iterdir() if item.name.endswith(".tmp")]


def _boom(*args, **kwargs):
    raise OSError("no space left on device")


def test_refinement_registry_round_trip(tmp_path):
    registry = RefinementRegistry(tmp_path / "refinement.json")
    analysis = EvidenceGapAnalysis("a", "w", "t", "o")
    plan = ImportRecommendationPlan("p", "w", "t")
    template = ImportTemplate("t", "generic_market_csv", "t", "d", [], [], [], "data/import_templates/generic_market_csv.csv")
    registry.register_gap_analysis(analysis); registry.register_import_plan(plan); registry.register_template(template)
    assert registry.get_gap_analysis("a").analysis_id == "a" and registry.get_import_plan("p").plan_id == "p" and registry.get_template("t").template_id == "t"


def test_corrupt_registry_is_empty(tmp_path):
    path = tmp_path / "bad.json"; path.write_text("{bad", encoding="utf-8")
    registry = RefinementRegistry(path)
    assert registry.list_gap_analyses() == []


def test_missing_file_starts_empty_and_writes_normally(tmp_path):
    path = tmp_path / "refinement.json"
    registry = RefinementRegistry(path)
    assert registry.load_error is None and registry.list_gap_analyses() == []
    registry.register_gap_analysis(_gap())
    assert json.loads(path.read_text(encoding="utf-8"))["gap_analyses"]["a"]["analysis_id"] == "a"


@pytest.mark.parametrize("raw_bytes", [b"{bad", b"\xff\xfe\x00"], ids=["malformed_json", "not_utf8"])
def test_corrupt_file_is_preserved_and_blocks_writes(tmp_path, raw_bytes):
    path = tmp_path / "refinement.json"
    path.write_bytes(raw_bytes)
    registry = RefinementRegistry(path)
    assert registry.load_error == "registry_corrupt"
    assert registry.list_gap_analyses() == []
    with pytest.raises(RegistryPersistenceError) as caught:
        registry.register_gap_analysis(_gap())
    assert caught.value.reason == "registry_writes_blocked"
    assert path.read_bytes() == raw_bytes
    assert _temp_leftovers(tmp_path) == []


@pytest.mark.parametrize("name,payload", INVALID_STATE_CASES, ids=[name for name, _ in INVALID_STATE_CASES])
def test_invalid_shape_is_refused_and_preserved(tmp_path, name, payload):
    path = tmp_path / "refinement.json"
    raw = json.dumps(payload).encode("utf-8")
    path.write_bytes(raw)
    registry = RefinementRegistry(path)
    assert registry.load_error == "registry_invalid"
    assert registry.list_gap_analyses() == []
    with pytest.raises(RegistryPersistenceError, match="registry_writes_blocked"):
        registry.register_gap_analysis(_gap("b"))
    assert path.read_bytes() == raw


def test_unreadable_registry_is_refused_and_not_overwritten(tmp_path, monkeypatch):
    path = tmp_path / "refinement.json"
    original = json.dumps({"gap_analyses": {"a": VALID_GAP}}).encode("utf-8")
    path.write_bytes(original)

    def deny(self, *args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(refinement_module.Path, "read_text", deny)
    registry = RefinementRegistry(path)
    assert registry.load_error == "registry_unreadable"
    with pytest.raises(RegistryPersistenceError, match="registry_writes_blocked"):
        registry.register_gap_analysis(_gap("b"))
    monkeypatch.undo()
    assert path.read_bytes() == original


def test_directory_at_registry_path_is_refused_and_left_alone(tmp_path):
    path = tmp_path / "refinement.json"
    path.mkdir()
    registry = RefinementRegistry(path)
    assert registry.load_error == "registry_unreadable"
    with pytest.raises(RegistryPersistenceError, match="registry_writes_blocked"):
        registry.register_gap_analysis(_gap())
    assert path.is_dir()


@pytest.mark.parametrize("failing_call", ["replace", "fsync"])
def test_failed_write_raises_keeps_original_and_rolls_back_memory(tmp_path, monkeypatch, failing_call):
    path = tmp_path / "refinement.json"
    registry = RefinementRegistry(path)
    registry.register_gap_analysis(_gap("a"))
    original = path.read_bytes()
    monkeypatch.setattr(refinement_module.os, failing_call, _boom)
    with pytest.raises(RegistryPersistenceError) as caught:
        registry.register_gap_analysis(_gap("b"))
    monkeypatch.undo()
    assert caught.value.reason == "registry_write_failed"
    assert str(caught.value) == "registry_write_failed"
    assert caught.value.__cause__ is None
    assert str(tmp_path) not in str(caught.value)
    assert registry.get_gap_analysis("b") is None and registry.get_gap_analysis("a") is not None
    assert path.read_bytes() == original
    assert _temp_leftovers(tmp_path) == []


def test_failed_first_write_creates_no_file(tmp_path, monkeypatch):
    path = tmp_path / "refinement.json"
    registry = RefinementRegistry(path)
    monkeypatch.setattr(refinement_module.os, "replace", _boom)
    with pytest.raises(RegistryPersistenceError, match="registry_write_failed"):
        registry.register_gap_analysis(_gap())
    monkeypatch.undo()
    assert not path.exists() and _temp_leftovers(tmp_path) == []
    assert registry.get_gap_analysis("a") is None


def test_clear_for_tests_refuses_to_erase_a_corrupt_registry(tmp_path):
    path = tmp_path / "refinement.json"
    path.write_text("{bad", encoding="utf-8")
    registry = RefinementRegistry(path)
    with pytest.raises(RegistryPersistenceError, match="registry_writes_blocked"):
        registry.clear_for_tests()
    assert path.read_text(encoding="utf-8") == "{bad"


def test_restart_reloads_every_successful_write(tmp_path):
    path = tmp_path / "refinement.json"
    first = RefinementRegistry(path)
    first.register_gap_analysis(_gap("a"))
    first.register_import_plan(ImportRecommendationPlan("p", "w", "t"))
    first.register_template(_template())
    restarted = RefinementRegistry(path)
    assert restarted.load_error is None
    assert restarted.get_gap_analysis("a") is not None and restarted.get_import_plan("p") is not None and restarted.get_template("t") is not None


def test_operator_repair_then_restart_resumes_writes(tmp_path):
    path = tmp_path / "refinement.json"
    path.write_text("{bad", encoding="utf-8")
    assert RefinementRegistry(path).load_error == "registry_corrupt"
    path.write_text(json.dumps({"gap_analyses": {"a": VALID_GAP}}), encoding="utf-8")
    repaired = RefinementRegistry(path)
    assert repaired.load_error is None and repaired.get_gap_analysis("a") is not None
    repaired.register_gap_analysis(_gap("b"))
    assert RefinementRegistry(path).get_gap_analysis("b") is not None


def test_successful_writes_leave_only_the_registry_file(tmp_path):
    path = tmp_path / "refinement.json"
    registry = RefinementRegistry(path)
    for n in range(3):
        registry.register_gap_analysis(_gap(f"g{n}"))
    assert sorted(item.name for item in tmp_path.iterdir()) == ["refinement.json"]


def test_concurrent_registrations_are_all_persisted(tmp_path):
    path = tmp_path / "refinement.json"
    registry = RefinementRegistry(path)
    errors = []

    def worker(n):
        try:
            for i in range(25):
                registry.register_gap_analysis(_gap(f"g{n}-{i}"))
        except Exception as exc:  # noqa: BLE001 — collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(RefinementRegistry(path).gap_analyses) == 200
    assert _temp_leftovers(tmp_path) == []
