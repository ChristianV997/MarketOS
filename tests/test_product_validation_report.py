from evaluation.commerce.product_validation_report import generate,markdown
def test_fixture_report_is_client_safe():
 r=generate(client_name="Demo Client").to_dict()
 assert r['client_name_optional']=='Demo Client' and r['read_only'] and not r['network_calls'] and not r['mutated']
 assert r['evidence_mode']=='fixture_demo' and 'profit guarantee' in r['operator_disclaimer']
def test_markdown_has_required_client_sections():
 text=markdown(generate().to_dict())
 for section in ('Executive Summary','Candidate Ranking','Supplier Readiness','Risk Flags','Disclaimer'):assert section in text

def test_credential_shaped_evidence_pass_through_is_redacted_not_forwarded():
    """Upstream evidence pillars are free text (scraped ad hooks, reviews,
    voice-of-customer objections) and are not guaranteed to be pre-sanitized
    before reaching this client-facing report. A credential-shaped string
    copied into a consumer-attention hook or pain point used to flow straight
    through into the client report verbatim -- reproduced here before the fix
    with `sk-...`/`-----BEGIN...`-shaped values surviving into the final
    to_dict() output. It must now be caught by the existing TrustOS
    client-workspace leakage detector and redacted, not silently forwarded."""
    import json

    consumer_attention = {
        "evidence_mode": "fixture_demo", "top_candidate_id": "c1",
        "candidates": [{
            "candidate_id": "c1", "query": "widget",
            "evidence": [{"platform": "tiktok", "hook": "Bearer sk-secret-leaked-123", "evidence_mode": "fixture"}],
            "score": {
                "overall_consumer_attention": 0.7, "source_diversity": 0.6, "objection_density": 0.1,
                "recommended_ad_angles": ["convenience"],
                "creative_hooks": [{"hook": "Bearer sk-secret-leaked-123"}],
                "voice_of_customer": {"pain_points": ["leaked secret sk-abc123"], "desired_outcomes": [], "objections": []},
                "recommendation": "validate_supplier_first",
            },
        }],
    }
    opportunity_synthesis = {
        "overall_recommendation": "validate_supplier_first",
        "client_summary": "Demo candidate needs more supplier proof.",
        "risk_profile": {}, "decision_thresholds": {}, "kill_scale_rules": {},
        "fourteen_day_validation_plan": [], "next_best_action": "expand_supplier_research",
    }
    report = generate(opportunity_synthesis=opportunity_synthesis, consumer_attention=consumer_attention).to_dict()
    blob = json.dumps(report)
    assert "sk-secret-leaked-123" not in blob
    assert "sk-abc123" not in blob
    assert report["appendix"]["client_safety_leakage_findings"] >= 1
