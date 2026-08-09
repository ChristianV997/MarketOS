from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any
from .market_models import _b
@dataclass
class ProductPositioning:
    positioning_id:str; workspace_id:str; product_name:str; category_name:str; likely_buyer:str="Buyer hypothesis requires validation"; primary_pain_point:str="Pain point not established"; core_promise:str="Hypothesis only"; differentiation_angles:list[str]=field(default_factory=list); bundle_ideas:list[str]=field(default_factory=list); upsell_ideas:list[str]=field(default_factory=list); variant_ideas:list[str]=field(default_factory=list); price_positioning:str="Price evidence unavailable"; creative_angles:list[str]=field(default_factory=list); objection_map:list[dict[str,Any]]=field(default_factory=list); evidence_basis:list[dict[str,Any]]=field(default_factory=list); limitations:list[str]=field(default_factory=list); metadata:dict[str,Any]=field(default_factory=dict)
    def to_dict(self): return {k:getattr(self,k) for k in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls,data): return cls(**{k:data[k] for k in cls.__dataclass_fields__ if k in data})
@dataclass
class ProductViabilityReport:
    report_id:str; workspace_id:str; product_name:str; category_name:str; title:str; viability_score:float=0; confidence_score:float=0; demand_fit_score:float=0; differentiation_score:float=0; margin_plausibility_score:float=0; supplier_plausibility_score:float=0; competition_risk_score:float=0; creative_potential_score:float=0; validation_readiness_score:float=0; failure_modes:list[str]=field(default_factory=list); strongest_reasons_to_test:list[str]=field(default_factory=list); strongest_reasons_to_reject_or_delay:list[str]=field(default_factory=list); missing_evidence:list[str]=field(default_factory=list); recommended_validation_tests:list[dict[str,Any]]=field(default_factory=list); recommended_imports:list[dict[str,Any]]=field(default_factory=list); positioning:ProductPositioning|None=None; created_at:float=field(default_factory=time.time); metadata:dict[str,Any]=field(default_factory=dict)
    def __post_init__(self):
        for key in ("viability_score","demand_fit_score","differentiation_score","margin_plausibility_score","supplier_plausibility_score","competition_risk_score","creative_potential_score","validation_readiness_score"): setattr(self,key,_b(getattr(self,key)))
        self.confidence_score=_b(self.confidence_score,0,1)
    def to_dict(self): return {k:(self.positioning.to_dict() if k=="positioning" and self.positioning else getattr(self,k)) for k in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls,data): data=dict(data); data["positioning"]=ProductPositioning.from_dict(data["positioning"]) if isinstance(data.get("positioning"),dict) else None; return cls(**{k:data[k] for k in cls.__dataclass_fields__ if k in data})
    def to_markdown(self): return f"# {self.title}\n\n**Viability:** `{self.viability_score:.1f}`  \n**Confidence:** `{self.confidence_score:.2f}`\n\n## Failure modes\n\n"+"\n".join(f"- {x}" for x in self.failure_modes)+"\n\n## Reasons to test\n\n"+"\n".join(f"- {x}" for x in self.strongest_reasons_to_test)+"\n\n## Missing evidence\n\n"+"\n".join(f"- {x}" for x in self.missing_evidence)+"\n\nPositioning and validation ideas are hypotheses, not sales or profitability claims.\n"
