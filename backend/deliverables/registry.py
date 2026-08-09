from __future__ import annotations
import json,os,threading
from pathlib import Path
from .package import DeliverablePackage,DeliverableArtifact
class DeliverableRegistry:
 def __init__(self,path=None): self.path=Path(path or os.getenv("MARKETOS_DELIVERABLE_STATE","state/deliverable_registry.json")); self.packages={}; self.artifacts={}; self.load()
 def register_package(self,x): self.packages[x.package_id]=x; self.save(); return x
 def update_package(self,x): return self.register_package(x)
 def get_package(self,x): return self.packages.get(x)
 def list_packages(self,workspace_id=None,package_type=None,status=None,limit=50): return sorted([x for x in self.packages.values() if (workspace_id is None or x.workspace_id==workspace_id) and (package_type is None or x.package_type==package_type) and (status is None or x.status==status)],key=lambda x:x.created_at,reverse=True)[:max(0,min(int(limit),500))]
 def register_artifact(self,package_id,artifact): self.artifacts[artifact.artifact_id]={"package_id":package_id,"artifact":artifact}; self.save(); return artifact
 def list_artifacts(self,package_id=None,artifact_type=None,limit=100): return [x["artifact"] for x in self.artifacts.values() if (package_id is None or x["package_id"]==package_id) and (artifact_type is None or x["artifact"].artifact_type==artifact_type)][:max(0,min(int(limit),1000))]
 def latest_package(self,workspace_id=None,package_type=None):
  x=self.list_packages(workspace_id,package_type,limit=1); return x[0] if x else None
 def clear_for_tests(self): self.packages.clear(); self.artifacts.clear(); self.save()
 def to_dict(self): return {"packages":{k:v.to_dict() for k,v in self.packages.items()},"artifacts":{k:{"package_id":v["package_id"],"artifact":v["artifact"].to_dict()} for k,v in self.artifacts.items()}}
 def load(self):
  try:
   if self.path.exists():
    d=json.loads(self.path.read_text(encoding="utf-8")); self.packages={k:DeliverablePackage.from_dict(v) for k,v in d.get("packages",{}).items()}; self.artifacts={k:{"package_id":v.get("package_id",""),"artifact":DeliverableArtifact.from_dict(v.get("artifact",{}))} for k,v in d.get("artifacts",{}).items()}
  except Exception: self.packages,self.artifacts={},{}
 def save(self):
  try: self.path.parent.mkdir(parents=True,exist_ok=True); t=self.path.with_suffix(".tmp"); t.write_text(json.dumps(self.to_dict(),indent=2,default=str),encoding="utf-8"); t.replace(self.path)
  except Exception: pass
_singleton=None; _lock=threading.Lock()
def get_deliverable_registry():
 global _singleton
 if _singleton is None:
  with _lock:
   if _singleton is None: _singleton=DeliverableRegistry()
 return _singleton
