from backend.intelligence.knowledge_graph import KnowledgeNode,KnowledgeEdge,KnowledgeGraphSnapshot
from backend.intelligence.knowledge_registry import KnowledgeRegistry
from backend.intelligence.strategic_priority_engine import build_strategic_priority_plan
from backend.intelligence.research_campaign_engine import build_research_campaign_plan
from backend.intelligence.executive_brief_engine import build_executive_brief
from backend.intelligence.executive_command_runner import run_executive_intelligence_cycle

def test_graph_models_and_registry(tmp_path):
    registry=KnowledgeRegistry(tmp_path/"graph.json");node=KnowledgeNode("n","opportunity","Desk","summary");registry.register_node(node);registry.register_edge(KnowledgeEdge("e","n","m","supports",rationale=["explicit"],provenance={"source":"test"}));assert registry.get_node("n").title=="Desk";assert registry.neighbors("n")==[]

def test_priority_and_campaign_are_safe():
    priority=build_strategic_priority_plan("intelligence-test")
    campaign=build_research_campaign_plan("intelligence-test")
    assert priority.priorities and all(0<=x.total_priority_score<=100 for x in priority.priorities)
    assert all(x.metadata.get("dry_run_only") or x.metadata.get("dry_run") for x in priority.priorities)
    assert campaign.metadata.get("dry_run_only") is True

def test_initial_brief_has_limitations():
    result=build_executive_brief("intelligence-brief-test",include_html=True)
    brief=result["brief"]
    assert brief["metadata"]["dry_run_only"] is True
    assert "No live action" in __import__("backend.intelligence.executive_brief",fromlist=["ExecutiveBrief"]).ExecutiveBrief.from_dict(brief).to_markdown()

def test_command_runner_returns_partial_safe_outputs():
    result=run_executive_intelligence_cycle("intelligence-cycle-test")
    assert result["status"] in {"completed","partial"} and result["executive_brief"]
