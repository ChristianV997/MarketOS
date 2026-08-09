from __future__ import annotations
import time, uuid
from dataclasses import dataclass, field
from typing import Any
def _b(v,lo,hi):
 try:return max(lo,min(float(v),hi))
 except (TypeError,ValueError):return lo
@dataclass
class KnowledgeNode:
 node_id:str; node_type:str; title:str; summary:str; workspace_id:str="default"; source_object_id:str=""; source_registry:str=""; score:float=0; confidence:float=0; status:str=""; tags:list[str]=field(default_factory=list); created_at:float=field(default_factory=time.time); updated_at:float=field(default_factory=time.time); metadata:dict[str,Any]=field(default_factory=dict)
 def __post_init__(self):self.score=_b(self.score,0,100);self.confidence=_b(self.confidence,0,1)
 def to_dict(self):return {k:getattr(self,k) for k in self.__dataclass_fields__}
 @classmethod
 def from_dict(cls,d):return cls(**{k:d[k] for k in cls.__dataclass_fields__ if k in d})
@dataclass
class KnowledgeEdge:
 edge_id:str; from_node_id:str; to_node_id:str; relation_type:str; weight:float=1; confidence:float=.5; rationale:list[str]=field(default_factory=list); provenance:dict[str,Any]=field(default_factory=dict); created_at:float=field(default_factory=time.time); metadata:dict[str,Any]=field(default_factory=dict)
 def __post_init__(self):self.weight=_b(self.weight,0,1);self.confidence=_b(self.confidence,0,1)
 def to_dict(self):return {k:getattr(self,k) for k in self.__dataclass_fields__}
 @classmethod
 def from_dict(cls,d):return cls(**{k:d[k] for k in cls.__dataclass_fields__ if k in d})
@dataclass
class KnowledgeGraphSnapshot:
 snapshot_id:str; workspace_id:str; title:str; node_count:int=0; edge_count:int=0; node_type_counts:dict[str,int]=field(default_factory=dict); relation_type_counts:dict[str,int]=field(default_factory=dict); top_nodes:list[dict[str,Any]]=field(default_factory=list); isolated_nodes:list[dict[str,Any]]=field(default_factory=list); unresolved_nodes:list[dict[str,Any]]=field(default_factory=list); created_at:float=field(default_factory=time.time); metadata:dict[str,Any]=field(default_factory=dict)
 def to_dict(self):return {k:getattr(self,k) for k in self.__dataclass_fields__}
 @classmethod
 def from_dict(cls,d):return cls(**{k:d[k] for k in cls.__dataclass_fields__ if k in d})
 def to_markdown(self):return f"# {self.title}\n\nNodes: `{self.node_count}`  \nEdges: `{self.edge_count}`\n\n## Node types\n\n```json\n{self.node_type_counts}\n```\n\n## Top nodes\n\n"+"\n".join(f"- **{x.get('title')}** — `{x.get('node_type')}`" for x in self.top_nodes)+"\n\nThis graph is incomplete by design; relationships are only recorded when supported by persisted IDs.\n"
