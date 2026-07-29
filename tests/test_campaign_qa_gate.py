from backend.commerce.loop import CommerceLoop
from backend.commerce.contracts import CreativeBundle
from backend.agents.domain_agents import CampaignQAResult


def test_campaign_qa_gate_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MARKETOS_AGENT_QA_ENABLED", raising=False)
    bundle = CreativeBundle(product_id="p", creative_id="c", primary_text="Buy")
    checked, failures = CommerceLoop().quality_gate([bundle])
    assert checked == [bundle]
    assert failures == []


def test_campaign_qa_gate_fails_closed_on_rejection(monkeypatch):
    monkeypatch.setenv("MARKETOS_AGENT_QA_ENABLED", "true")

    async def reject(_request):
        return CampaignQAResult(approved=False, issues=["policy"])

    monkeypatch.setattr("backend.agents.domain_agents.run_campaign_qa", reject)
    bundle = CreativeBundle(product_id="p", creative_id="c", primary_text="Buy")
    checked, failures = CommerceLoop().quality_gate([bundle])
    assert "not_launchable" in checked[0].reasons
    assert failures == ["c:rejected"]
