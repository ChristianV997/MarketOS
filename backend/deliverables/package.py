from __future__ import annotations
import html, time
from dataclasses import dataclass, field
from typing import Any

@dataclass
class DeliverableSection:
    section_id: str; title: str; order: int; content_markdown: str; summary: str = ""; source_refs: list[dict[str,Any]]=field(default_factory=list); warnings: list[str]=field(default_factory=list); metadata: dict[str,Any]=field(default_factory=dict)
    def to_dict(self): return {k:getattr(self,k) for k in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls,d): return cls(**{k:d[k] for k in cls.__dataclass_fields__ if k in d})

@dataclass
class DeliverableArtifact:
    artifact_id: str; artifact_type: str; title: str; relative_path: str; content_type: str; created_at: float=field(default_factory=time.time); metadata: dict[str,Any]=field(default_factory=dict)
    def to_dict(self): return {k:getattr(self,k) for k in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls,d): return cls(**{k:d[k] for k in cls.__dataclass_fields__ if k in d})

@dataclass
class DeliverablePackage:
    package_id: str; workspace_id: str; package_type: str; title: str; objective: str; status: str="created"; source_sprint_id: str=""; source_snapshot_id: str=""; source_portfolio_report_id: str=""; source_discovery_ids: list[str]=field(default_factory=list); source_report_ids: list[str]=field(default_factory=list); source_scorecard_ids: list[str]=field(default_factory=list); source_opportunity_ids: list[str]=field(default_factory=list); sections: list[DeliverableSection]=field(default_factory=list); artifacts: list[DeliverableArtifact]=field(default_factory=list); executive_summary: str=""; recommendations: list[str]=field(default_factory=list); risk_flags: list[str]=field(default_factory=list); missing_evidence: list[str]=field(default_factory=list); next_actions: list[str]=field(default_factory=list); created_at: float=field(default_factory=time.time); finished_at: float|None=None; metadata: dict[str,Any]=field(default_factory=dict)
    def to_dict(self): return {k:[x.to_dict() for x in v] if k in {"sections","artifacts"} else v for k,v in ((k,getattr(self,k)) for k in self.__dataclass_fields__)}
    @classmethod
    def from_dict(cls,d):
        d=dict(d); d["sections"]=[DeliverableSection.from_dict(x) for x in d.get("sections",[])]; d["artifacts"]=[DeliverableArtifact.from_dict(x) for x in d.get("artifacts",[])]; return cls(**{k:d[k] for k in cls.__dataclass_fields__ if k in d})
    def to_markdown(self): return f"# {self.title}\n\n**Status:** `{self.status}`  \n**Objective:** {self.objective}\n\n## Executive summary\n\n{self.executive_summary}\n\n"+"\n\n".join(f"## {x.order}. {x.title}\n\n{x.content_markdown}" for x in sorted(self.sections,key=lambda x:x.order))+"\n\n## Recommendations\n\n"+"\n".join(f"- {x}" for x in self.recommendations)+"\n\n## Safety and limitations\n\nNo live launch or external action was executed. Evidence gaps and provenance limitations remain material.\n"
    def to_html_fragment(self): return "<article><h1>"+html.escape(self.title)+"</h1><p><strong>Status:</strong> "+html.escape(self.status)+"</p><h2>Executive summary</h2><p>"+html.escape(self.executive_summary)+"</p>"+"".join("<section><h2>"+html.escape(str(x.order))+". "+html.escape(x.title)+"</h2><pre>"+html.escape(x.content_markdown)+"</pre></section>" for x in sorted(self.sections,key=lambda x:x.order))+"<p><strong>Safety:</strong> No live launch or external action was executed.</p></article>"
