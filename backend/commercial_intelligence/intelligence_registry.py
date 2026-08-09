from __future__ import annotations
import json, os, threading
from pathlib import Path
from .evidence_features import EvidenceFeatureSet
from .market_models import MarketAttractivenessReport
from .product_models import ProductViabilityReport
class CommercialIntelligenceRegistry:
    def __init__(self,path=None): self.path=Path(path or os.getenv("MARKETOS_COMMERCIAL_INTELLIGENCE_STATE","state/commercial_intelligence_registry.json")); self.feature_sets={}; self.market_reports={}; self.product_reports={}; self.load()
    def to_dict(self): return {"feature_sets":{k:v.to_dict() for k,v in self.feature_sets.items()},"market_reports":{k:v.to_dict() for k,v in self.market_reports.items()},"product_reports":{k:v.to_dict() for k,v in self.product_reports.items()}}
    def load(self):
        try:
            raw=json.loads(self.path.read_text(encoding="utf-8")); self.feature_sets={k:EvidenceFeatureSet.from_dict(v) for k,v in raw.get("feature_sets",{}).items()}; self.market_reports={k:MarketAttractivenessReport.from_dict(v) for k,v in raw.get("market_reports",{}).items()}; self.product_reports={k:ProductViabilityReport.from_dict(v) for k,v in raw.get("product_reports",{}).items()}
        except Exception: pass
    def save(self):
        try: self.path.parent.mkdir(parents=True,exist_ok=True); tmp=self.path.with_suffix(".tmp"); tmp.write_text(json.dumps(self.to_dict(),indent=2,default=str),encoding="utf-8"); tmp.replace(self.path)
        except Exception: pass
    def register_feature_set(self,x): self.feature_sets[x.feature_set_id]=x; self.save(); return x
    def get_feature_set(self,x): return self.feature_sets.get(x)
    def list_feature_sets(self,workspace_id=None,limit=50): return sorted([x for x in self.feature_sets.values() if workspace_id is None or x.workspace_id==workspace_id],key=lambda x:x.created_at,reverse=True)[:min(int(limit),500)]
    def register_market_report(self,x): self.market_reports[x.report_id]=x; self.save(); return x
    def get_market_report(self,x): return self.market_reports.get(x)
    def list_market_reports(self,workspace_id=None,category_name=None,limit=50): return sorted([x for x in self.market_reports.values() if (workspace_id is None or x.workspace_id==workspace_id) and (category_name is None or x.category_name.lower()==category_name.lower())],key=lambda x:x.created_at,reverse=True)[:min(int(limit),500)]
    def latest_market_report(self,workspace_id=None,category_name=None): return next(iter(self.list_market_reports(workspace_id,category_name,1)),None)
    def register_product_report(self,x): self.product_reports[x.report_id]=x; self.save(); return x
    def get_product_report(self,x): return self.product_reports.get(x)
    def list_product_reports(self,workspace_id=None,product_name=None,category_name=None,opportunity_id=None,limit=50): return sorted([x for x in self.product_reports.values() if (workspace_id is None or x.workspace_id==workspace_id) and (product_name is None or x.product_name.lower()==product_name.lower()) and (category_name is None or x.category_name.lower()==category_name.lower()) and (opportunity_id is None or x.metadata.get("opportunity_id")==opportunity_id)],key=lambda x:x.created_at,reverse=True)[:min(int(limit),500)]
    def latest_product_report(self,workspace_id=None,product_name=None,category_name=None,opportunity_id=None): return next(iter(self.list_product_reports(workspace_id,product_name,category_name,opportunity_id,1)),None)
    def clear_for_tests(self): self.feature_sets.clear(); self.market_reports.clear(); self.product_reports.clear(); self.save()
_singleton=None; _lock=threading.Lock()
def get_commercial_intelligence_registry():
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None: _singleton=CommercialIntelligenceRegistry()
    return _singleton
