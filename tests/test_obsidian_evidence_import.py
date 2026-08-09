from backend.discovery.evidence_import import EvidenceImportJob, EvidenceSourceQuality
from backend.obsidian.sync import sync_evidence_import_note


def test_evidence_note_is_optional(monkeypatch):
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    job = EvidenceImportJob("i", "w", "source", "local_file", "x.csv", "generic_market_csv")
    quality = EvidenceSourceQuality("source", "local_file", 50, .5)
    assert sync_evidence_import_note(job, quality)["status"] == "skipped"
