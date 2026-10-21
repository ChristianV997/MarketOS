import json
import threading

import pytest

import backend.discovery.import_registry as import_module
from backend.discovery.evidence_import import EvidenceImportJob, EvidenceSourceQuality
from backend.discovery.import_registry import EvidenceImportRegistry, RegistryPersistenceError

VALID_JOB = EvidenceImportJob("i", "w", "source", "local_file", "x.csv", "generic_market_csv", "completed", created_at=1).to_dict()
VALID_QUALITY = EvidenceSourceQuality("source", "local_file", 50, .5).to_dict()
INVALID_STATE_CASES = [
    ("top_level_list", []),
    ("section_not_object", {"import_jobs": []}),
    ("job_not_object", {"import_jobs": {"i": "text"}}),
    ("job_missing_fields", {"import_jobs": {"i": {"import_id": "i"}}}),
    ("job_key_differs_from_identity", {"import_jobs": {"other": VALID_JOB}}),
    ("quality_not_object", {"source_quality": {"source": 3}}),
    ("quality_key_differs_from_identity", {"source_quality": {"other": VALID_QUALITY}}),
]


def _job(import_id="i"):
    return EvidenceImportJob(import_id, "w", "source", "local_file", "x.csv", "generic_market_csv", "completed", created_at=1)


def _quality():
    return EvidenceSourceQuality("source", "local_file", 50, .5)


def _temp_leftovers(directory):
    return [item.name for item in directory.iterdir() if item.name.endswith(".tmp")]


def _boom(*args, **kwargs):
    raise OSError("no space left on device")


def test_import_registry_persists_and_filters(tmp_path):
    registry = EvidenceImportRegistry(tmp_path / "imports.json")
    job = EvidenceImportJob("i", "w", "source", "local_file", "x.csv", "generic_market_csv", "completed", created_at=1)
    quality = EvidenceSourceQuality("source", "local_file", 50, .5)
    registry.register_import_job(job); registry.register_source_quality(quality)
    assert registry.list_import_jobs(workspace_id="w")[0].import_id == "i"
    assert registry.get_source_quality("source").quality_score == 50


def test_corrupt_registry_is_empty(tmp_path):
    path = tmp_path / "bad.json"; path.write_text("{bad", encoding="utf-8")
    registry = EvidenceImportRegistry(path)
    assert registry.list_import_jobs() == [] and registry.list_source_quality() == []


def test_missing_file_starts_empty_and_writes_normally(tmp_path):
    path = tmp_path / "imports.json"
    registry = EvidenceImportRegistry(path)
    assert registry.load_error is None and registry.list_import_jobs() == []
    registry.register_import_job(_job())
    assert json.loads(path.read_text(encoding="utf-8"))["import_jobs"]["i"]["import_id"] == "i"


@pytest.mark.parametrize("raw_bytes", [b"{bad", b"\xff\xfe\x00"], ids=["malformed_json", "not_utf8"])
def test_corrupt_file_is_preserved_and_blocks_writes(tmp_path, raw_bytes):
    path = tmp_path / "imports.json"
    path.write_bytes(raw_bytes)
    registry = EvidenceImportRegistry(path)
    assert registry.load_error == "registry_corrupt"
    assert registry.list_import_jobs() == []
    with pytest.raises(RegistryPersistenceError) as caught:
        registry.register_import_job(_job())
    assert caught.value.reason == "registry_writes_blocked"
    assert path.read_bytes() == raw_bytes
    assert _temp_leftovers(tmp_path) == []


@pytest.mark.parametrize("name,payload", INVALID_STATE_CASES, ids=[name for name, _ in INVALID_STATE_CASES])
def test_invalid_shape_is_refused_and_preserved(tmp_path, name, payload):
    path = tmp_path / "imports.json"
    raw = json.dumps(payload).encode("utf-8")
    path.write_bytes(raw)
    registry = EvidenceImportRegistry(path)
    assert registry.load_error == "registry_invalid"
    assert registry.list_import_jobs() == [] and registry.list_source_quality() == []
    with pytest.raises(RegistryPersistenceError, match="registry_writes_blocked"):
        registry.register_import_job(_job("new"))
    assert path.read_bytes() == raw


def test_malformed_record_beside_valid_ones_is_not_silently_dropped(tmp_path):
    path = tmp_path / "imports.json"
    raw = json.dumps({"import_jobs": {"good": VALID_JOB, "bad": "not-a-dict"}}).encode("utf-8")
    path.write_bytes(raw)
    registry = EvidenceImportRegistry(path)
    assert registry.load_error == "registry_invalid"
    assert registry.get_import_job("good") is None
    with pytest.raises(RegistryPersistenceError, match="registry_writes_blocked"):
        registry.register_import_job(_job("new"))
    assert path.read_bytes() == raw


def test_unreadable_registry_is_refused_and_not_overwritten(tmp_path, monkeypatch):
    path = tmp_path / "imports.json"
    original = json.dumps({"import_jobs": {"i": VALID_JOB}}).encode("utf-8")
    path.write_bytes(original)

    def deny(self, *args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(import_module.Path, "read_text", deny)
    registry = EvidenceImportRegistry(path)
    assert registry.load_error == "registry_unreadable"
    with pytest.raises(RegistryPersistenceError, match="registry_writes_blocked"):
        registry.register_import_job(_job("new"))
    monkeypatch.undo()
    assert path.read_bytes() == original


def test_directory_at_registry_path_is_refused_and_left_alone(tmp_path):
    path = tmp_path / "imports.json"
    path.mkdir()
    registry = EvidenceImportRegistry(path)
    assert registry.load_error == "registry_unreadable"
    with pytest.raises(RegistryPersistenceError, match="registry_writes_blocked"):
        registry.register_source_quality(_quality())
    assert path.is_dir()


@pytest.mark.parametrize("failing_call", ["replace", "fsync"])
def test_failed_write_raises_keeps_original_and_rolls_back_memory(tmp_path, monkeypatch, failing_call):
    path = tmp_path / "imports.json"
    registry = EvidenceImportRegistry(path)
    registry.register_import_job(_job("i"))
    original = path.read_bytes()
    monkeypatch.setattr(import_module.os, failing_call, _boom)
    with pytest.raises(RegistryPersistenceError) as caught:
        registry.register_import_job(_job("new"))
    monkeypatch.undo()
    assert caught.value.reason == "registry_write_failed"
    assert str(caught.value) == "registry_write_failed"
    assert caught.value.__cause__ is None
    assert str(tmp_path) not in str(caught.value)
    assert registry.get_import_job("new") is None and registry.get_import_job("i") is not None
    assert path.read_bytes() == original
    assert _temp_leftovers(tmp_path) == []


def test_failed_source_quality_write_rolls_back_memory(tmp_path, monkeypatch):
    path = tmp_path / "imports.json"
    registry = EvidenceImportRegistry(path)
    monkeypatch.setattr(import_module.os, "replace", _boom)
    with pytest.raises(RegistryPersistenceError, match="registry_write_failed"):
        registry.register_source_quality(_quality())
    monkeypatch.undo()
    assert registry.get_source_quality("source") is None
    assert not path.exists() and _temp_leftovers(tmp_path) == []


def test_clear_for_tests_refuses_to_erase_a_corrupt_registry(tmp_path):
    path = tmp_path / "imports.json"
    path.write_text("{bad", encoding="utf-8")
    registry = EvidenceImportRegistry(path)
    with pytest.raises(RegistryPersistenceError, match="registry_writes_blocked"):
        registry.clear_for_tests()
    assert path.read_text(encoding="utf-8") == "{bad"


def test_restart_reloads_every_successful_write(tmp_path):
    path = tmp_path / "imports.json"
    first = EvidenceImportRegistry(path)
    first.register_import_job(_job("i"))
    first.register_source_quality(_quality())
    restarted = EvidenceImportRegistry(path)
    assert restarted.load_error is None
    assert restarted.get_import_job("i").import_id == "i" and restarted.get_source_quality("source").quality_score == 50


def test_operator_repair_then_restart_resumes_writes(tmp_path):
    path = tmp_path / "imports.json"
    path.write_text("{bad", encoding="utf-8")
    assert EvidenceImportRegistry(path).load_error == "registry_corrupt"
    path.write_text(json.dumps({"import_jobs": {"i": VALID_JOB}}), encoding="utf-8")
    repaired = EvidenceImportRegistry(path)
    assert repaired.load_error is None and repaired.get_import_job("i") is not None
    repaired.register_import_job(_job("new"))
    assert EvidenceImportRegistry(path).get_import_job("new") is not None


def test_successful_writes_leave_only_the_registry_file(tmp_path):
    path = tmp_path / "imports.json"
    registry = EvidenceImportRegistry(path)
    for n in range(3):
        registry.register_import_job(_job(f"i{n}"))
    assert sorted(item.name for item in tmp_path.iterdir()) == ["imports.json"]


def test_concurrent_registrations_are_all_persisted(tmp_path):
    path = tmp_path / "imports.json"
    registry = EvidenceImportRegistry(path)
    errors = []

    def worker(n):
        try:
            for i in range(25):
                registry.register_import_job(_job(f"i{n}-{i}"))
        except Exception as exc:  # noqa: BLE001 — collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(EvidenceImportRegistry(path).import_jobs) == 200
    assert _temp_leftovers(tmp_path) == []
