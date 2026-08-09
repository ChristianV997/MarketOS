from __future__ import annotations
import json,os,threading
from pathlib import Path
from .validation_sprint import ValidationSprint,ValidationScorecard
class ValidationSprintRegistry:
 def __init__(self,path=None): self.path=Path(path or os.getenv("MARKETOS_VALIDATION_SPRINT_STATE","state/validation_sprint_registry.json")); self.sprints={}; self.scorecards={}; self.load()
 def register_sprint(self,x): self.sprints[x.sprint_id]=x; self.save(); return x
 def update_sprint(self,x): return self.register_sprint(x)
 def get_sprint(self,x): return self.sprints.get(x)
 def list_sprints(self,workspace_id=None,status=None,limit=50): return sorted([x for x in self.sprints.values() if (workspace_id is None or x.workspace_id==workspace_id) and (status is None or x.status==status)],key=lambda x:x.created_at,reverse=True)[:max(0,min(int(limit),500))]
 def register_scorecard(self,x): self.scorecards[x.scorecard_id]=x; self.save(); return x
 def get_scorecard(self,x): return self.scorecards.get(x)
 def list_scorecards(self,workspace_id=None,opportunity_id=None,recommendation=None,limit=100): return [x for x in self.scorecards.values() if (workspace_id is None or self._workspace(x)==workspace_id) and (opportunity_id is None or x.opportunity_id==opportunity_id) and (recommendation is None or x.recommendation==recommendation)][:max(0,min(int(limit),1000))]
 def _workspace(self,x): return (x.metadata or {}).get("workspace_id","")
 def latest_sprint(self,workspace_id=None):
  x=self.list_sprints(workspace_id,limit=1); return x[0] if x else None
 def clear_for_tests(self): self.sprints.clear(); self.scorecards.clear(); self.save()
 def to_dict(self): return {"sprints":{k:v.to_dict() for k,v in self.sprints.items()},"scorecards":{k:v.to_dict() for k,v in self.scorecards.items()}}
 def load(self):
  try:
   if self.path.exists():
    d=json.loads(self.path.read_text(encoding="utf-8")); self.sprints={k:ValidationSprint.from_dict(v) for k,v in d.get("sprints",{}).items()}; self.scorecards={k:ValidationScorecard.from_dict(v) for k,v in d.get("scorecards",{}).items()}
  except Exception: self.sprints,self.scorecards={},{}
 def save(self):
  try: self.path.parent.mkdir(parents=True,exist_ok=True); t=self.path.with_suffix(".tmp"); t.write_text(json.dumps(self.to_dict(),indent=2,default=str),encoding="utf-8"); t.replace(self.path)
  except Exception: pass
_singleton=None; _lock=threading.Lock()
def get_validation_sprint_registry():
 global _singleton
 if _singleton is None:
  with _lock:
   if _singleton is None: _singleton=ValidationSprintRegistry()
 return _singleton
