def build_market_research_questions(report):
    return [f"What local or cached export can provide `{x}` evidence for `{report.category_name}`?" for x in report.missing_evidence] or [f"Which independent source could confirm or contradict the current signals for `{report.category_name}`?"]
def build_product_validation_tests(report):
    return [{"test_type":"manual_evidence_review","objective":f"Validate {report.product_name} against recorded evidence","inputs":["approved local/cache evidence","provenance"],"success_criteria":["Evidence basis is traceable","Limitations are recorded"],"safety":"No live customer, ad, payment, or commerce action."}]
def build_recommended_imports_from_intelligence(report): return [{"signal_type":x,"reason":f"Report lacks {x} evidence.","mode":"local_or_manual_import_only"} for x in report.missing_evidence]
def build_positioning_hypotheses(report): return [{"angle":x,"status":"hypothesis","evidence_basis":report.positioning.evidence_basis,"confidence":report.confidence_score} for x in report.positioning.differentiation_angles]
