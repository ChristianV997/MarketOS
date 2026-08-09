from pathlib import Path
from backend.discovery.category_discovery import discover_categories_from_evidence
from backend.discovery.local_dataset import load_local_evidence_dataset, parse_evidence_records


def test_category_scores_are_bounded_and_provenance_is_explicit():
    path = Path(__file__).parent / "fixtures" / "market_evidence_seed.json"
    run = discover_categories_from_evidence(parse_evidence_records(load_local_evidence_dataset(str(path))))
    assert run.category_opportunities
    assert all(0 <= item.score <= 100 for item in run.category_opportunities)
    assert run.metadata["real_market_claims"] is False
    assert "missing_evidence" in run.category_opportunities[0].to_dict()
