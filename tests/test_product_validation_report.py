from evaluation.commerce.product_validation_report import generate,markdown
def test_fixture_report_is_client_safe():
 r=generate(client_name="Demo Client").to_dict()
 assert r['client_name_optional']=='Demo Client' and r['read_only'] and not r['network_calls'] and not r['mutated']
 assert r['evidence_mode']=='fixture_demo' and 'profit guarantee' in r['operator_disclaimer']
def test_markdown_has_required_client_sections():
 text=markdown(generate().to_dict())
 for section in ('Executive Summary','Candidate Ranking','Supplier Readiness','Risk Flags','Disclaimer'):assert section in text
