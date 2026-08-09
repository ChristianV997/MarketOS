from __future__ import annotations
from .market_analyzer import analyze_market_category
from .product_analyzer import analyze_product_viability
def run_commercial_intelligence_cycle(workspace_id="default",category_name=None,product_name=None,opportunity_id=None,include_market=True,include_product=True):
    market=None; product=None; warnings=[]
    try:
        if include_market: market=analyze_market_category(workspace_id,category_name,opportunity_id)
        if include_product and (product_name or opportunity_id or category_name): product=analyze_product_viability(workspace_id,product_name,category_name,opportunity_id)
    except Exception as exc: warnings.append(f"commercial_intelligence_partial:{type(exc).__name__}:{exc}")
    return {"feature_set":None,"market_report":market.to_dict() if market else None,"product_report":product.to_dict() if product else None,"warnings":warnings,"status":"completed" if market or product else "partial"}
