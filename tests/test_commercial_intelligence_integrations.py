def test_gate_semantics_remain_separate_and_graph_imports_intelligence():
    from backend.discovery.opportunity_pipeline import TRANSITIONS
    from backend.intelligence.knowledge_graph_builder import build_knowledge_graph_snapshot
    assert "launch_candidate" in TRANSITIONS["validation_ready"]
    result=build_knowledge_graph_snapshot("commercial-intelligence-test",include_evidence=False,include_reports=False,include_deliverables=False,limit_per_type=1)
    assert result["status"] == "completed"
