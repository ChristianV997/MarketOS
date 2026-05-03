"""Tests for backend.observability.entropy_metrics."""
from backend.observability.entropy_metrics import measure_entropy
from backend.observability.schemas.entropy_report import EntropyReport


def test_measure_entropy_returns_report():
    r = measure_entropy(workspace="test")
    assert isinstance(r, EntropyReport)


def test_entropy_report_has_id():
    r = measure_entropy(workspace="test")
    assert r.report_id
    assert len(r.report_id) > 0


def test_entropy_overall_in_range():
    r = measure_entropy(workspace="test")
    assert 0.0 <= r.overall_entropy <= 1.0


def test_entropy_consolidation_urgency():
    r = measure_entropy(workspace="test")
    assert r.consolidation_urgency in ("low", "medium", "high", "critical")


def test_entropy_to_dict_keys():
    r = measure_entropy(workspace="test")
    d = r.to_dict()
    assert "report_id" in d
    assert "overall_entropy" in d
    assert "consolidation_urgency" in d
    assert "workspace" in d


def test_entropy_vector_fields_default():
    r = EntropyReport(report_id="test01", workspace="default", window_s=3600.0)
    r.compute_aggregate()
    assert r.vector_coverage == 0.0
    assert r.vector_fragmentation == 0.0
