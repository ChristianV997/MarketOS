from __future__ import annotations
import json, os, threading
from pathlib import Path
from .opportunity_pipeline import Opportunity, OpportunityStageTransition, OpportunityPipelineSnapshot

class OpportunityRegistry:
    def __init__(self, path=None):
        self.path = Path(path or os.getenv("MARKETOS_OPPORTUNITY_STATE", "state/opportunity_pipeline_registry.json")); self.opportunities={}; self.transitions={}; self.snapshots={}; self._lock=threading.RLock(); self.load()
    def register_opportunity(self, item): self.opportunities[item.opportunity_id]=item; self.save(); return item
    def get_opportunity(self, item_id): return self.opportunities.get(item_id)
    def list_opportunities(self, workspace_id=None, stage=None, opportunity_type=None, recommendation=None, limit=100):
        items=[x for x in self.opportunities.values() if (workspace_id is None or x.workspace_id==workspace_id) and (stage is None or x.stage==stage) and (opportunity_type is None or x.opportunity_type==opportunity_type) and (recommendation is None or x.recommendation==recommendation)]
        return sorted(items,key=lambda x:(-x.score,x.name,x.opportunity_id))[:max(0,min(int(limit),1000))]
    def update_opportunity(self,item): return self.register_opportunity(item)
    def register_transition(self,item): self.transitions[item.transition_id]=item; self.save(); return item
    def list_transitions(self,workspace_id=None,opportunity_id=None,limit=100):
        items=[x for x in self.transitions.values() if (workspace_id is None or x.workspace_id==workspace_id) and (opportunity_id is None or x.opportunity_id==opportunity_id)]
        return sorted(items,key=lambda x:(x.created_at,x.transition_id),reverse=True)[:max(0,min(int(limit),1000))]
    def register_snapshot(self,item): self.snapshots[item.snapshot_id]=item; self.save(); return item
    def get_snapshot(self,item_id): return self.snapshots.get(item_id)
    def list_snapshots(self,workspace_id=None,limit=50): return sorted([x for x in self.snapshots.values() if workspace_id is None or x.workspace_id==workspace_id],key=lambda x:(x.created_at,x.snapshot_id),reverse=True)[:max(0,min(int(limit),500))]
    def latest_snapshot(self,workspace_id=None):
        items=self.list_snapshots(workspace_id,1); return items[0] if items else None
    def clear_for_tests(self): self.opportunities.clear(); self.transitions.clear(); self.snapshots.clear(); self.save()
    def to_dict(self): return {"opportunities":{k:v.to_dict() for k,v in self.opportunities.items()},"transitions":{k:v.to_dict() for k,v in self.transitions.items()},"snapshots":{k:v.to_dict() for k,v in self.snapshots.items()}}
    def load(self):
        try:
            if not self.path.exists(): return
            raw=json.loads(self.path.read_text(encoding="utf-8")); self.opportunities={k:Opportunity.from_dict(v) for k,v in raw.get("opportunities",{}).items()}; self.transitions={k:OpportunityStageTransition.from_dict(v) for k,v in raw.get("transitions",{}).items()}; self.snapshots={k:OpportunityPipelineSnapshot.from_dict(v) for k,v in raw.get("snapshots",{}).items()}
        except Exception: self.opportunities,self.transitions,self.snapshots={},{},{}
    def save(self):
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True); tmp=self.path.with_suffix(self.path.suffix+".tmp"); tmp.write_text(json.dumps(self.to_dict(),indent=2,default=str),encoding="utf-8"); tmp.replace(self.path)
        except Exception: pass
_singleton=None; _lock=threading.Lock()
def get_opportunity_registry():
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None: _singleton=OpportunityRegistry()
    return _singleton
