from __future__ import annotations
import time
from dataclasses import dataclass,field
from typing import Any
def d(x):return {k:getattr(x,k) for k in x.__dataclass_fields__}
@dataclass
class WorkflowStage:
 stage_id:str;stage_name:str;order:int;status:str="pending";started_at:float|None=None;finished_at:float|None=None;input_summary:dict[str,Any]=field(default_factory=dict);output_summary:dict[str,Any]=field(default_factory=dict);produced_object_ids:list[dict[str,Any]]=field(default_factory=list);warnings:list[str]=field(default_factory=list);errors:list[str]=field(default_factory=list);blocked_reasons:list[str]=field(default_factory=list);retry_count:int=0;max_retries:int=1;metadata:dict[str,Any]=field(default_factory=dict)
 def to_dict(self):return d(self)
 @classmethod
 def from_dict(cls,x):return cls(**{k:x[k] for k in cls.__dataclass_fields__ if k in x})
@dataclass
class WorkflowCheckpoint:
 checkpoint_id:str;workflow_id:str;stage_name:str;stage_status:str;checkpoint_type:str;state_summary:dict[str,Any]=field(default_factory=dict);produced_object_ids:list[dict[str,Any]]=field(default_factory=list);recoverable:bool=True;replayable:bool=True;created_at:float=field(default_factory=time.time);metadata:dict[str,Any]=field(default_factory=dict)
 def to_dict(self):return d(self)
 @classmethod
 def from_dict(cls,x):return cls(**{k:x[k] for k in cls.__dataclass_fields__ if k in x})
@dataclass
class WorkflowRun:
 workflow_id:str;workspace_id:str;workflow_type:str;title:str;objective:str;status:str="created";stages:list[WorkflowStage]=field(default_factory=list);checkpoints:list[WorkflowCheckpoint]=field(default_factory=list);current_stage:str="";input_payload:dict[str,Any]=field(default_factory=dict);final_output:dict[str,Any]=field(default_factory=dict);produced_object_ids:list[dict[str,Any]]=field(default_factory=list);safety_flags:list[str]=field(default_factory=list);warnings:list[str]=field(default_factory=list);errors:list[str]=field(default_factory=list);started_at:float|None=None;finished_at:float|None=None;created_at:float=field(default_factory=time.time);metadata:dict[str,Any]=field(default_factory=dict)
 def to_dict(self):return {k:[x.to_dict() for x in v] if k in {"stages","checkpoints"} else v for k,v in ((k,getattr(self,k)) for k in self.__dataclass_fields__)}
 @classmethod
 def from_dict(cls,x):
  x=dict(x);x["stages"]=[WorkflowStage.from_dict(v) for v in x.get("stages",[])];x["checkpoints"]=[WorkflowCheckpoint.from_dict(v) for v in x.get("checkpoints",[])];return cls(**{k:x[k] for k in cls.__dataclass_fields__ if k in x})
 def to_markdown(self):return f"# {self.title}\n\n**Status:** `{self.status}`  \n**Current stage:** `{self.current_stage}`\n\n"+"\n".join(f"- `{x.order}` **{x.stage_name}** — `{x.status}`" for x in self.stages)+"\n\nNo live action is permitted by this workflow.\n"
@dataclass
class WorkflowTimelineEvent:
 event_id:str;workflow_id:str;workspace_id:str;stage_name:str;event_type:str;message:str;severity:str="info";object_refs:list[dict[str,Any]]=field(default_factory=list);created_at:float=field(default_factory=time.time);metadata:dict[str,Any]=field(default_factory=dict)
 def to_dict(self):return d(self)
 @classmethod
 def from_dict(cls,x):return cls(**{k:x[k] for k in cls.__dataclass_fields__ if k in x})
