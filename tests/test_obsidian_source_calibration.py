from backend.discovery.source_calibration import CalibrationRun
from backend.obsidian.sync import sync_source_calibration_note


def test_calibration_note_optional(monkeypatch):
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    assert sync_source_calibration_note(CalibrationRun("c", "w", "t", "o", status="partial"))["status"] == "skipped"
