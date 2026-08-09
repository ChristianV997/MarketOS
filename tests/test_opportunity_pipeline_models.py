from backend.discovery.opportunity_pipeline import Opportunity, OpportunityPipelineSnapshot
from backend.discovery.opportunity_gates import evaluate_opportunity_gates

def test_opportunity_bounds_and_serializes():
    item = Opportunity("o1", "w", "category", "Home Fitness", "Home Fitness", score=120, confidence=-1)
    assert item.score == 100 and item.confidence == 0
    assert Opportunity.from_dict(item.to_dict()).name == "Home Fitness"

def test_discovered_with_gaps_requests_evidence():
    item = Opportunity("o1", "w", "category", "Home Fitness", "Home Fitness", missing_evidence=["demand_proxy"], gap_ids=["g1"])
    result = evaluate_opportunity_gates(item, [])
    assert result["recommended_transition"] == "evidence_requested"

def test_product_requires_cost_evidence_before_validation():
    item = Opportunity("o1", "w", "product_hypothesis", "Fitness accessory", "Home Fitness", stage="evidence_enriched", recommendation="investigate", score=70, confidence=.7)
    records = [type("R", (), {"entity_name":"Fitness accessory", "signal_type":s, "provenance":{}})() for s in ("demand_proxy", "competition_proxy")]
    result = evaluate_opportunity_gates(item, records)
    assert "missing_product_cost_or_price_evidence" in result["failed_gates"]

def test_synthetic_evidence_cannot_be_launch_candidate():
    item = Opportunity("o1", "w", "category", "Home Fitness", "Home Fitness", stage="validation_ready", score=90, confidence=.9)
    records = [type("R", (), {"entity_name":"Home Fitness", "signal_type":"demand_proxy", "provenance":{"not_real_market_data":True}})()]
    result = evaluate_opportunity_gates(item, records, [type("Report", (), {"service_name":"product_research"})()])
    assert result["recommended_transition"] != "launch_candidate"

def test_snapshot_round_trip():
    snapshot = OpportunityPipelineSnapshot("s", "w", "Pipeline", [Opportunity("o", "w", "category", "x", "x")])
    assert OpportunityPipelineSnapshot.from_dict(snapshot.to_dict()).opportunities[0].name == "x"
