from __future__ import annotations
import json,os,threading
from pathlib import Path
from .strategic_priority import StrategicPriorityPlan
from .research_campaign import ResearchCampaignPlan
from .executive_brief import ExecutiveBrief
class IntelligenceRegistry:
 def __init__(self,path=None):self.path=Path(path or os.getenv("MARKETOS_INTELLIGENCE_STATE","state/executive_intelligence_registry.json"));self.priority_plans={};self.campaign_plans={};self.briefs={};self.load()
 def register_priority_plan(self,x):self.priority_plans[x.plan_id]=x;self.save();return x
 def get_priority_plan(self,x):return self.priority_plans.get(x)
 def list_priority_plans(self,workspace_id=None,limit=50):return list(reversed([x for x in self.priority_plans.values() if workspace_id is None or x.workspace_id==workspace_id]))[:max(0,min(int(limit),500))]
 def register_campaign_plan(self,x):self.campaign_plans[x.plan_id]=x;self.save();return x
 def get_campaign_plan(self,x):return self.campaign_plans.get(x)
 def list_campaign_plans(self,workspace_id=None,limit=50):return list(reversed([x for x in self.campaign_plans.values() if workspace_id is None or x.workspace_id==workspace_id]))[:max(0,min(int(limit),500))]
 def register_executive_brief(self,x):self.briefs[x.brief_id]=x;self.save();return x
 def get_executive_brief(self,x):return self.briefs.get(x)
 def list_executive_briefs(self,workspace_id=None,limit=50):return sorted([x for x in self.briefs.values() if workspace_id is None or x.workspace_id==workspace_id],key=lambda x:x.created_at,reverse=True)[:max(0,min(int(limit),500))]
 def latest_executive_brief(self,workspace_id=None):
  x=self.list_executive_briefs(workspace_id,1);return x[0] if x else None
 def clear_for_tests(self):self.priority_plans.clear();self.campaign_plans.clear();self.briefs.clear();self.save()
 def to_dict(self):return {"priority_plans":{k:v.to_dict() for k,v in self.priority_plans.items()},"campaign_plans":{k:v.to_dict() for k,v in self.campaign_plans.items()},"briefs":{k:v.to_dict() for k,v in self.briefs.items()}}
 def load(self):
  try:
   if self.path.exists():
    d=json.loads(self.path.read_text(encoding="utf-8"));self.priority_plans={k:StrategicPriorityPlan.from_dict(v) for k,v in d.get("priority_plans",{}).items()};self.campaign_plans={k:ResearchCampaignPlan.from_dict(v) for k,v in d.get("campaign_plans",{}).items()};self.briefs={k:ExecutiveBrief.from_dict(v) for k,v in d.get("briefs",{}).items()}
  except Exception:self.priority_plans,self.campaign_plans,self.briefs={},{},{}
 def save(self):
  try:self.path.parent.mkdir(parents=True,exist_ok=True);t=self.path.with_suffix(".tmp");t.write_text(json.dumps(self.to_dict(),indent=2,default=str),encoding="utf-8");t.replace(self.path)
  except Exception:pass
_singleton=None;_lock=threading.Lock()
def get_intelligence_registry():
 global _singleton
 if _singleton is None:
  with _lock:
   if _singleton is None:_singleton=IntelligenceRegistry()
 return _singleton
