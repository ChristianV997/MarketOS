from types import SimpleNamespace
from backend.discovery.discovery_comparison import compare_category_discoveries


def test_comparison_tracks_movements_and_cautious_language():
    before = SimpleNamespace(discovery_id="old", evidence_count=1, category_opportunities=[SimpleNamespace(category_name="x", rank=1, score=40, recommendation="hold")])
    current = SimpleNamespace(discovery_id="new", evidence_count=3, category_opportunities=[SimpleNamespace(category_name="x", rank=2, score=55, recommendation="investigate"), SimpleNamespace(category_name="y", rank=1, score=60, recommendation="hold")])
    result = compare_category_discoveries(before, current, "w")
    assert result.evidence_count_change == 2 and result.new_categories == ["y"]
    assert "not causal" in result.to_markdown()


def test_empty_comparison_safe():
    result = compare_category_discoveries(None, None)
    assert result.status == "completed" and not result.category_movements
