import json
import tempfile
from pathlib import Path

import pytest

from api.routes.discovery import market_discovery
from backend.discovery.local_dataset import load_local_evidence_dataset, parse_evidence_records

CANARY = "zz-canary-local-dataset-root"
REPO = Path(__file__).resolve().parents[1]


def _canary_payload() -> str:
    return json.dumps({
        "dataset_id": "outside-root-dataset",
        "source_name": "local_dataset",
        "provenance": {"type": "synthetic_fixture", "not_real_market_data": True},
        "records": [{
            "entity_type": "category",
            "entity_name": CANARY,
            "signal_type": "demand_proxy",
            "value": 0.5,
            "weight": 1.0,
            "confidence": 0.5,
        }],
    })


def test_seed_fixture_parses():
    path = Path(__file__).resolve().parent / "fixtures" / "market_evidence_seed.json"
    dataset = load_local_evidence_dataset(str(path))
    records = parse_evidence_records(dataset)
    assert records and all(record.provenance.get("not_real_market_data") for record in records)


def test_missing_provenance_rejected():
    with tempfile.TemporaryDirectory(dir=REPO) as inside:
        path = Path(inside) / "bad.json"
        path.write_text(json.dumps({"dataset_id": "x", "source_name": "local_dataset", "records": []}), encoding="utf-8")
        with pytest.raises(ValueError, match="dataset_provenance_required"):
            load_local_evidence_dataset(str(path.resolve()))


def test_traversal_rejected():
    with pytest.raises(ValueError, match="dataset_path_traversal_blocked"):
        load_local_evidence_dataset("../outside.json")


def test_absolute_outside_root_is_not_read(tmp_path, monkeypatch):
    outside = tmp_path / "outside_dataset.json"
    outside.write_text(_canary_payload(), encoding="utf-8")
    opened: list[Path] = []
    real_open = Path.open

    def tracking_open(self, *args, **kwargs):
        opened.append(Path(self))
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracking_open)
    with pytest.raises(ValueError, match="dataset_path_outside_project_root") as caught:
        load_local_evidence_dataset(str(outside))
    assert CANARY not in str(caught.value)
    assert outside.resolve() not in {item.resolve() for item in opened}

    body = market_discovery({"dataset_paths": [str(outside)], "run_validation_services": False})
    rendered = json.dumps(body)
    assert body["status"] == "blocked"
    assert CANARY not in rendered
    assert any(item.endswith(":ValueError") and item.startswith("dataset_failed:") for item in body["warnings"])


def test_symlink_inside_project_cannot_escape(tmp_path, monkeypatch):
    outside = tmp_path / "outside_dataset.json"
    outside.write_text(_canary_payload(), encoding="utf-8")
    opened: list[Path] = []
    real_open = Path.open

    def tracking_open(self, *args, **kwargs):
        opened.append(Path(self))
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracking_open)
    with tempfile.TemporaryDirectory(dir=REPO) as inside:
        link = Path(inside) / "inside_link.json"
        link.symlink_to(outside)
        with pytest.raises(ValueError, match="dataset_path_outside_project_root") as caught:
            load_local_evidence_dataset(str(link))
        assert CANARY not in str(caught.value)
        assert outside.resolve() not in {item.resolve() for item in opened}
