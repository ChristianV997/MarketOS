from __future__ import annotations
import time
from dataclasses import dataclass,field
from typing import Any
@dataclass
class ResearchCampaign:
 campaign_id:str;workspace_id:str;title:str;objective:str;category_name:str;status:str="proposed";related_opportunity_ids:list[str]=field(default_factory=list);related_gap_ids:list[str]=field(default_factory=list);related_acquisition_plan_ids:list[str]=field(default_factory=list);related_import_recommendation_ids:list[str]=field(default_factory=list);related_priority_ids:list[str]=field(default_factory=list);required_evidence:list[dict[str,Any]]=field(default_factory=list);planned_steps:list[dict[str,Any]]=field(default_factory=list);success_criteria:list[str]=field(default_factory=list);stop_criteria:list[str]=field(default_factory=list);expected_information_gain:float=0;effort_score:float=50;risk_flags:list[str]=field(default_factory=list);created_at:float=field(default_factory=time.time);updated_at:float=field(default_factory=time.time);metadata:dict[str,Any]=field(default_factory=dict)
 def to_dict(self):return {k:getattr(self,k) for k in self.__dataclass_fields__}
 @classmethod
 def from_dict(cls,d):return cls(**{k:d[k] for k in cls.__dataclass_fields__ if k in d})
@dataclass
class ResearchCampaignPlan:
 plan_id:str;workspace_id:str;campaigns:list[ResearchCampaign]=field(default_factory=list);summary:str="";recommended_sequence:list[str]=field(default_factory=list);created_at:float=field(default_factory=time.time);metadata:dict[str,Any]=field(default_factory=dict)
 def to_dict(self):return {k:[x.to_dict() for x in v] if k=="campaigns" else v for k,v in ((k,getattr(self,k)) for k in self.__dataclass_fields__)}
 @classmethod
 def from_dict(cls,d):d=dict(d);d["campaigns"]=[ResearchCampaign.from_dict(x) for x in d.get("campaigns",[])];return cls(**{k:d[k] for k in cls.__dataclass_fields__ if k in d})
 def to_markdown(self):return f"# Research Campaign Plan\n\n{self.summary}\n\n"+"\n".join(f"- **{x.title}** — `{x.status}`; gain `{x.expected_information_gain:.1f}`" for x in self.campaigns)+"\n\nAll campaigns are manual/cache-only and dry-run.\n"
