"""Round trip: every generated starter template imports through the existing normalizer as advertised.

Callers: pytest. Data: synthetic placeholder rows written to a temporary working directory only.
"""
import pytest

from backend.discovery.evidence_normalizer import normalize_imported_evidence
from backend.discovery.import_recommendation import _FIELDS
from backend.discovery.import_templates import create_import_template


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize("parser", sorted(_FIELDS))
def test_unedited_template_round_trips_through_the_normalizer(workdir, parser):
    item = create_import_template(parser)
    result = normalize_imported_evidence(item.file_path, parser, item.metadata["source_name"])
    assert result.import_job.status == "completed"
    assert result.records
    assert all(record.entity_name.startswith("PLACEHOLDER") for record in result.records)
    assert all(record.provenance["parser_type"] == parser for record in result.records)


def test_unedited_generic_template_is_not_silently_empty(workdir):
    # Previously the placeholder signal was unknown, so the importer dropped the row and still reported completed.
    item = create_import_template("generic_market_csv")
    result = normalize_imported_evidence(item.file_path, "generic_market_csv", item.metadata["source_name"])
    assert result.import_job.status == "completed"
    assert len(result.records) >= 1
