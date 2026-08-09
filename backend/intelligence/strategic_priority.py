from __future__ import annotations
import time
from dataclasses import dataclass,field
from typing import Any
def b(v):
 try:return max(0,min(float(v),100))
 except:return 0
@dataclass
class StrategicPriority:
 priority_id:str;workspace_id:str;priority_type:str;title:str;description:str;urgency_score:float=0;leverage_score:float=0;confidence_score:float=0;information_gain_score:float=0;effort_score:float=50;risk_score:float=0;total_priority_score:float=0;related_node_ids:list[str]=field(default_factory=list);related_opportunity_ids:list[str]=field(default_factory=list);related_gap_ids:list[str]=field(default_factory=list);related_report_ids:list[str]=field(default_factory=list);recommended_action:str="";action_endpoint:str="";action_payload:dict[str,Any]=field(default_factory=dict);status:str="open";rationale:list[str]=field(default_factory=list);created_at:float=field(default_factory=time.time);metadata:dict[str,Any]=field(default_factory=dict)
 def __post_init__(self):
  for k in ("urgency_score","leverage_score","confidence_score","information_gain_score","effort_score","risk_score","total_priority_score"):setattr(self,k,b(getattr(self,k)))
 def to_dict(self):return {k:getattr(self,k) for k in self.__dataclass_fields__}
 @classmethod
 def from_dict(cls,d):return cls(**{k:d[k] for k in cls.__dataclass_fields__ if k in d})
@dataclass
class StrategicPriorityPlan:
 plan_id:str;workspace_id:str;title:str;objective:str;priorities:list[StrategicPriority]=field(default_factory=list);portfolio_summary:dict[str,Any]=field(default_factory=dict);top_risks:list[str]=field(default_factory=list);top_blockers:list[str]=field(default_factory=list);recommended_sequence:list[str]=field(default_factory=list);created_at:float=field(default_factory=time.time);metadata:dict[str,Any]=field(default_factory=dict)
 def to_dict(self):return {k:[x.to_dict() for x in v] if k=="priorities" else v for k,v in ((k,getattr(self,k)) for k in self.__dataclass_fields__)}
 @classmethod
 def from_dict(cls,d):d=dict(d);d["priorities"]=[StrategicPriority.from_dict(x) for x in d.get("priorities",[])];return cls(**{k:d[k] for k in cls.__dataclass_fields__ if k in d})
 def to_markdown(self):return f"# {self.title}\n\n{self.objective}\n\n"+"\n".join(f"- **{x.title}** — `{x.total_priority_score:.1f}` — {x.recommended_action}" for x in self.priorities)+"\n\nPriorities are dry-run planning recommendations; no live action is authorized.\n"
