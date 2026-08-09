from backend.creative_intelligence.claim_safety import detect_prohibited_claims,sanitize_creative_claim

def test_claim_safety_blocks_unsafe_language_without_mutation():
    claim="Guaranteed 10x ROAS, only today; read this testimonial"
    result=sanitize_creative_claim(claim,[])
    assert result["status"]=="blocked" and result["safe_text"]!=claim
    assert detect_prohibited_claims("The best choice")["status"]=="caution"
    assert claim=="Guaranteed 10x ROAS, only today; read this testimonial"
