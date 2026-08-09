from pathlib import Path
from backend.discovery.category_discovery import discover_categories_from_evidence
from backend.discovery.local_dataset import load_local_evidence_dataset, parse_evidence_records
from backend.discovery.product_hypothesis import generate_product_hypotheses


def test_hypotheses_are_bounded_and_conservative():
    path = Path(__file__).parent / "fixtures" / "market_evidence_seed.json"
    records = parse_evidence_records(load_local_evidence_dataset(str(path)))
    run = generate_product_hypotheses(discover_categories_from_evidence(records), records, max_per_category=1, max_total=3)
    assert 0 < len(run.hypotheses) <= 3
    assert all("product_not_validated" in item.risk_flags for item in run.hypotheses)
    assert all(item.metadata["synthetic_or_cached_only"] for item in run.hypotheses)
