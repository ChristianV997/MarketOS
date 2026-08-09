from backend.discovery.evidence_import import EvidenceImportJob, EvidenceSourceQuality
from backend.discovery.import_registry import EvidenceImportRegistry


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
