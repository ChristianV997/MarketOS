from pathlib import Path
from backend.discovery.market_discovery_runner import run_market_discovery


def test_discovery_notes_are_optional(monkeypatch, tmp_path):
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    path = Path(__file__).parent / "fixtures" / "market_evidence_seed.json"
    result = run_market_discovery(dataset_paths=[str(path)], run_validation_services=False)
    assert result["obsidian"]["category"]["status"] == "skipped"
    assert result["obsidian"]["hypotheses"]["status"] == "skipped"
