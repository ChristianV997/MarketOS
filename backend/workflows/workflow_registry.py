from __future__ import annotations
import json,os,threading
from pathlib import Path
from .workflow_models import WorkflowRun,WorkflowCheckpoint,WorkflowTimelineEvent
class WorkflowRegistry:
 def __init__(self,path=None):self.path=Path(path or os.getenv("MARKETOS_WORKFLOW_STATE","state/workflow_registry.json"));self.workflows={};self.checkpoints={};self.timeline={};self.load()
 def register_workflow(self,x):self.workflows[x.workflow_id]=x;self.save();return x
 def update_workflow(self,x):return self.register_workflow(x)
 def get_workflow(self,x):return self.workflows.get(x)
 def list_workflows(self,workspace_id=None,workflow_type=None,status=None,limit=50):return sorted([x for x in self.workflows.values() if (workspace_id is None or x.workspace_id==workspace_id) and (workflow_type is None or x.workflow_type==workflow_type) and (status is None or x.status==status)],key=lambda x:x.created_at,reverse=True)[:max(0,min(int(limit),500))]
 def register_checkpoint(self,x):self.checkpoints[x.checkpoint_id]=x;self.save();return x
 def list_checkpoints(self,workflow_id=None,stage_name=None,limit=200):return sorted([x for x in self.checkpoints.values() if (workflow_id is None or x.workflow_id==workflow_id) and (stage_name is None or x.stage_name==stage_name)],key=lambda x:x.created_at,reverse=True)[:max(0,min(int(limit),1000))]
 def latest_checkpoint(self,workflow_id,stage_name=None):
  x=self.list_checkpoints(workflow_id,stage_name,1);return x[0] if x else None
 def register_timeline_event(self,x):self.timeline[x.event_id]=x;self.save();return x
 def list_timeline(self,workflow_id=None,workspace_id=None,limit=500):return sorted([x for x in self.timeline.values() if (workflow_id is None or x.workflow_id==workflow_id) and (workspace_id is None or x.workspace_id==workspace_id)],key=lambda x:x.created_at)[:max(0,min(int(limit),2000))]
 def latest_workflow(self,workspace_id=None,workflow_type=None):
  x=self.list_workflows(workspace_id,workflow_type,limit=1);return x[0] if x else None
 def clear_for_tests(self):self.workflows.clear();self.checkpoints.clear();self.timeline.clear();self.save()
 def to_dict(self):return {"workflows":{k:v.to_dict() for k,v in self.workflows.items()},"checkpoints":{k:v.to_dict() for k,v in self.checkpoints.items()},"timeline":{k:v.to_dict() for k,v in self.timeline.items()}}
 def load(self):
  try:
   if self.path.exists():
    x=json.loads(self.path.read_text(encoding="utf-8"));self.workflows={k:WorkflowRun.from_dict(v) for k,v in x.get("workflows",{}).items()};self.checkpoints={k:WorkflowCheckpoint.from_dict(v) for k,v in x.get("checkpoints",{}).items()};self.timeline={k:WorkflowTimelineEvent.from_dict(v) for k,v in x.get("timeline",{}).items()}
  except Exception:self.workflows,self.checkpoints,self.timeline={},{},{}
 def save(self):
  try:self.path.parent.mkdir(parents=True,exist_ok=True);t=self.path.with_suffix(".tmp");t.write_text(json.dumps(self.to_dict(),indent=2,default=str),encoding="utf-8");t.replace(self.path)
  except Exception:pass
_singleton=None;_lock=threading.Lock()
def get_workflow_registry():
 global _singleton
 if _singleton is None:
  with _lock:
   if _singleton is None:_singleton=WorkflowRegistry()
 return _singleton
