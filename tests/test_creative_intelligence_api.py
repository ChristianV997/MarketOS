from api.routes.creative_intelligence import validate_claim

def test_creative_claim_api_is_local_and_blocks_performance_claims():
    result=validate_claim({"claim":"Guaranteed profit"})
    assert result["status"]=="blocked"
