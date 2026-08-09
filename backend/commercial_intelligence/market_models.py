from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any
from .evidence_features import EvidenceFeature

def _b(v, low=0, high=100):
    try: return max(low,min(float(v),high))
    except (TypeError,ValueError): return low
@dataclass
class MarketSignalSummary:
    summary_id:str; workspace_id:str; category_name:str; demand_score:float=0; trend_score:float=0; saturation_score:float=0; competition_score:float=0; seasonality_score:float=0; pricing_signal_score:float=0; supplier_signal_score:float=0; creative_signal_score:float=0; evidence_confidence:float=0; evidence_coverage:dict[str,float]=field(default_factory=dict); strongest_signals:list[str]=field(default_factory=list); weakest_signals:list[str]=field(default_factory=list); contradictions:list[str]=field(default_factory=list); limitations:list[str]=field(default_factory=list); provenance_refs:list[dict[str,Any]]=field(default_factory=list); metadata:dict[str,Any]=field(default_factory=dict)
    def __post_init__(self):
        for key in ("demand_score","trend_score","saturation_score","competition_score","seasonality_score","pricing_signal_score","supplier_signal_score","creative_signal_score"): setattr(self,key,_b(getattr(self,key)))
        self.evidence_confidence=_b(self.evidence_confidence,0,1)
    def to_dict(self): return {k:getattr(self,k) for k in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls,data): return cls(**{k:data[k] for k in cls.__dataclass_fields__ if k in data})
@dataclass
class MarketAttractivenessReport:
    report_id:str; workspace_id:str; category_name:str; title:str; attractiveness_score:float=0; confidence_score:float=0; market_structure:str="insufficient evidence"; demand_read:str="insufficient evidence"; trend_read:str="insufficient evidence"; competition_read:str="insufficient evidence"; saturation_read:str="insufficient evidence"; seasonality_read:str="insufficient evidence"; pricing_read:str="insufficient evidence"; supplier_read:str="insufficient evidence"; creative_read:str="insufficient evidence"; customer_read:str="insufficient evidence"; major_risks:list[str]=field(default_factory=list); missing_evidence:list[str]=field(default_factory=list); recommended_research_questions:list[str]=field(default_factory=list); recommended_actions:list[dict[str,Any]]=field(default_factory=list); signal_summary:MarketSignalSummary|None=None; created_at:float=field(default_factory=time.time); metadata:dict[str,Any]=field(default_factory=dict)
    def __post_init__(self): self.attractiveness_score=_b(self.attractiveness_score); self.confidence_score=_b(self.confidence_score,0,1)
    def to_dict(self): return {k:(self.signal_summary.to_dict() if k=="signal_summary" and self.signal_summary else getattr(self,k)) for k in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls,data): data=dict(data); data["signal_summary"]=MarketSignalSummary.from_dict(data["signal_summary"]) if isinstance(data.get("signal_summary"),dict) else None; return cls(**{k:data[k] for k in cls.__dataclass_fields__ if k in data})
    def to_markdown(self): return f"# {self.title}\n\n**Attractiveness:** `{self.attractiveness_score:.1f}`  \n**Confidence:** `{self.confidence_score:.2f}`\n\n## Reads\n\n- Demand: {self.demand_read}\n- Trend: {self.trend_read}\n- Competition: {self.competition_read}\n- Saturation: {self.saturation_read}\n- Pricing: {self.pricing_read}\n\n## Risks, missing evidence, and limitations\n\n"+"\n".join(f"- {x}" for x in self.major_risks+self.missing_evidence+(self.signal_summary.limitations if self.signal_summary else []))+"\n\nThis report is evidence-constrained and does not claim market size, demand, profitability, or ROI.\n"
