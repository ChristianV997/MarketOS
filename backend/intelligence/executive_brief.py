from __future__ import annotations
import html,time
from dataclasses import dataclass,field
from typing import Any
@dataclass
class ExecutiveBrief:
 brief_id:str;workspace_id:str;title:str;period_label:str;summary:str;what_changed:list[str]=field(default_factory=list);top_priorities:list[dict[str,Any]]=field(default_factory=list);top_opportunities:list[dict[str,Any]]=field(default_factory=list);validation_summary:dict[str,Any]=field(default_factory=dict);evidence_summary:dict[str,Any]=field(default_factory=dict);deliverable_summary:dict[str,Any]=field(default_factory=dict);risk_summary:list[str]=field(default_factory=list);blocker_summary:list[str]=field(default_factory=list);recommended_next_actions:list[str]=field(default_factory=list);linked_priority_plan_id:str="";linked_campaign_plan_id:str="";linked_knowledge_snapshot_id:str="";created_at:float=field(default_factory=time.time);metadata:dict[str,Any]=field(default_factory=dict)
 def to_dict(self):return {k:getattr(self,k) for k in self.__dataclass_fields__}
 @classmethod
 def from_dict(cls,d):return cls(**{k:d[k] for k in cls.__dataclass_fields__ if k in d})
 def to_markdown(self):return f"# {self.title}\n\n**Period:** `{self.period_label}`\n\n## Summary\n\n{self.summary}\n\n## What changed\n\n"+"\n".join(f"- {x}" for x in self.what_changed)+"\n\n## Top priorities\n\n"+"\n".join(f"- **{x.get('title')}** — {x.get('recommended_action')}" for x in self.top_priorities)+"\n\n## Risks and blockers\n\n"+"\n".join(f"- {x}" for x in self.risk_summary+self.blocker_summary)+"\n\n## Next actions\n\n"+"\n".join(f"- {x}" for x in self.recommended_next_actions)+"\n\nNo live action was executed; this brief is evidence-constrained and planning-only.\n"
 def to_html_fragment(self):return "<article><h1>"+html.escape(self.title)+"</h1><p>"+html.escape(self.summary)+"</p><h2>Next actions</h2><ul>"+"".join("<li>"+html.escape(x)+"</li>" for x in self.recommended_next_actions)+"</ul><p>No live action was executed.</p></article>"
