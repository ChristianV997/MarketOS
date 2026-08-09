from __future__ import annotations
import uuid
from .research_campaign import ResearchCampaign,ResearchCampaignPlan
from backend.discovery.opportunity_registry import get_opportunity_registry
from backend.discovery.refinement_registry import get_refinement_registry
from backend.discovery.acquisition_registry import get_acquisition_registry
def build_research_campaign_plan(workspace_id="default",max_campaigns=10):
 opp=get_opportunity_registry().list_opportunities(workspace_id,limit=500); gaps=[g for a in get_refinement_registry().list_gap_analyses(workspace_id,50) for g in a.gaps]; plans=get_acquisition_registry().list_plans(workspace_id,limit=500); campaigns=[]
 groups={}
 for g in gaps:groups.setdefault(g.category_name or g.entity_name,[]).append(g)
 for category,items in sorted(groups.items(),key=lambda x:(-max(g.priority_score for g in x[1]),x[0]))[:max(0,min(int(max_campaigns),20))]:
  related=[x for x in opp if x.category_name.lower()==category.lower()]; related_plans=[p.plan_id for p in plans if set(p.related_gap_ids)&{g.gap_id for g in items}]; campaigns.append(ResearchCampaign("campaign_"+uuid.uuid5(uuid.NAMESPACE_URL,f"{workspace_id}:{category}").hex[:16],workspace_id,f"Evidence campaign: {category}",f"Reduce uncertainty for {category}",category,related_opportunity_ids=[x.opportunity_id for x in related],related_gap_ids=[g.gap_id for g in items],related_acquisition_plan_ids=related_plans,required_evidence=[{"signal":g.missing_signal_type,"severity":g.severity} for g in items],planned_steps=[{"action":"complete_manual_export","endpoint":"/api/discovery/import-and-run","dry_run":True},{"action":"rerun_refinement","endpoint":"/api/discovery/refinement-cycle","dry_run":True}],success_criteria=["Required fields are present and provenance is recorded.","Discovery gaps are reassessed after import."],stop_criteria=["Source is unavailable or unverified.","Input contains secrets or unauthorized personal data."],expected_information_gain=max(g.priority_score for g in items),effort_score=45,risk_flags=["no_live_source_enabled"],metadata={"dry_run_only":True}))
 return ResearchCampaignPlan("campaign_plan_"+uuid.uuid4().hex[:16],workspace_id,campaigns,"Campaigns group high-priority evidence gaps into bounded manual/cache work.",[x.campaign_id for x in campaigns],metadata={"dry_run_only":True})
