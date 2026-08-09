import json
from pathlib import Path
import pytest
from backend.discovery.local_dataset import load_local_evidence_dataset, parse_evidence_records


def test_seed_fixture_parses():
    path = Path(__file__).parent / "fixtures" / "market_evidence_seed.json"
    dataset = load_local_evidence_dataset(str(path))
    records = parse_evidence_records(dataset)
    assert records and all(record.provenance.get("not_real_market_data") for record in records)


def test_missing_provenance_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"dataset_id": "x", "source_name": "local_dataset", "records": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_local_evidence_dataset(str(path))


def test_traversal_rejected():
    with pytest.raises(ValueError):
        load_local_evidence_dataset("../outside.json")
