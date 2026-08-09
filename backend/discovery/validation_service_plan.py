from __future__ import annotations
from backend.organization.service_contract import get_service_contract_registry

def build_validation_service_plan(opportunity):
    names=["product_research","unit_economics","customer_intelligence","profit_stack_advisor"] if opportunity.opportunity_type=="product_hypothesis" else ["customer_intelligence"]
    metadata=getattr(opportunity,"metadata",{}) or {}; has_cost=any(k in metadata for k in ("retail_price","supplier_cost","shipping_cost","price"))
    if "unit_economics" in names and not has_cost: names.remove("unit_economics")
    registry=get_service_contract_registry(); result=[]
    for name in names:
        check=registry.validate_safe_to_call(name, "product" if name=="product_research" else "growth" if name=="customer_intelligence" else "finance" if name=="profit_stack_advisor" else "product")
        if check.get("allowed"): result.append(name)
    return result

def build_service_inputs_for_opportunity(opportunity, service_name, evidence_records=None):
    data=getattr(opportunity,"metadata",{}) or {}; common={"dry_run":True,"read_only":True,"metadata":{"opportunity_id":opportunity.opportunity_id,"evidence_ids":opportunity.evidence_ids,"source_stage":opportunity.stage}}
    if service_name=="product_research": return {"product_name":opportunity.name,"category":opportunity.category_name,**common,**({"retail_price":data["retail_price"]} if data.get("retail_price") is not None else {})}
    if service_name=="customer_intelligence": return {"business_type":"ecommerce_brand","vertical":"ecommerce_brand","category":opportunity.category_name,**common}
    if service_name=="profit_stack_advisor": return {"business_name":opportunity.name,"business_model":"own_ecommerce",**common}
    if service_name=="unit_economics":
        if not data.get("product") or not data.get("offer"): return {"_missing_inputs":["product","offer"],**common}
        return {"product":data["product"],"offer":data["offer"],**common}
    return {"_unsupported":[service_name],**common}
