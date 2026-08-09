from __future__ import annotations
import json, os, threading
from pathlib import Path
from .creative_models import BuyerPsychologyMap, CreativeAngle, CreativeHook, UGCBrief, StoryboardOutline, LandingPageClaimMap, CreativeTestMatrix, CreativeIntelligenceReport

_KINDS={"buyer_maps":BuyerPsychologyMap,"angles":CreativeAngle,"hooks":CreativeHook,"ugc_briefs":UGCBrief,"storyboards":StoryboardOutline,"claim_maps":LandingPageClaimMap,"test_matrices":CreativeTestMatrix,"reports":CreativeIntelligenceReport}
class CreativeIntelligenceRegistry:
    def __init__(self,path=None):
        self.path=Path(path or os.getenv("MARKETOS_CREATIVE_INTELLIGENCE_STATE","state/creative_intelligence_registry.json")); [setattr(self,k,{}) for k in _KINDS]; self.load()
    def load(self):
        try:
            data=json.loads(self.path.read_text(encoding="utf-8"))
            for k,c in _KINDS.items(): setattr(self,k,{i:c.from_dict(v) for i,v in data.get(k,{}).items()})
        except Exception: pass
    def save(self):
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True); tmp=self.path.with_suffix(".tmp"); tmp.write_text(json.dumps({k:{i:x.to_dict() for i,x in getattr(self,k).items()} for k in _KINDS},indent=2,default=str),encoding="utf-8");tmp.replace(self.path)
        except Exception: pass
    def _reg(self,k,x): getattr(self,k)[getattr(x,next(i for i in x.__dataclass_fields__ if i.endswith("_id")))]=x;self.save();return x
    def _get(self,k,i): return getattr(self,k).get(i)
    def _list(self,k,workspace_id=None,opportunity_id=None,product_name=None,category_name=None,angle_id=None,limit=50):
        xs=list(getattr(self,k).values())
        def ok(x):
            return (workspace_id is None or x.workspace_id==workspace_id) and (opportunity_id is None or getattr(x,"opportunity_id",None)==opportunity_id) and (product_name is None or getattr(x,"product_name","").lower()==product_name.lower()) and (category_name is None or getattr(x,"category_name","").lower()==category_name.lower()) and (angle_id is None or getattr(x,"angle_id",None)==angle_id)
        return sorted(filter(ok,xs),key=lambda x:getattr(x,"created_at",0),reverse=True)[:min(max(int(limit),0),500)]
    def clear_for_tests(self):
        for k in _KINDS:getattr(self,k).clear()
        self.save()

for _plural,_cls in _KINDS.items():
    _singular={"buyer_maps":"buyer_map","angles":"angle","hooks":"hook","ugc_briefs":"ugc_brief","storyboards":"storyboard","claim_maps":"claim_map","test_matrices":"test_matrix","reports":"report"}[_plural]
    setattr(CreativeIntelligenceRegistry,f"register_{_singular}",lambda self,x,k=_plural:self._reg(k,x))
    setattr(CreativeIntelligenceRegistry,f"get_{_singular}",lambda self,i,k=_plural:self._get(k,i))
    setattr(CreativeIntelligenceRegistry,f"list_{_plural}",lambda self,workspace_id=None,opportunity_id=None,product_name=None,category_name=None,angle_id=None,limit=50,k=_plural:self._list(k,workspace_id,opportunity_id,product_name,category_name,angle_id,limit))
def _latest(self,workspace_id=None,opportunity_id=None,product_name=None,category_name=None): return next(iter(self.list_reports(workspace_id,opportunity_id,product_name,category_name,limit=1)),None)
CreativeIntelligenceRegistry.latest_report=_latest
_singleton=None;_lock=threading.Lock()
def get_creative_registry():
 global _singleton
 if _singleton is None:
  with _lock:
   if _singleton is None:_singleton=CreativeIntelligenceRegistry()
 return _singleton
