from __future__ import annotations
def execute_workflow_stage(workflow,stage,context):
 p=workflow.input_payload;ws=workflow.workspace_id;name=stage.stage_name
 if name=="import_evidence":
  if not p.get("import_paths") and not p.get("imports"):return {"status":"skipped","output":{},"warnings":["no_imports_provided; using persisted evidence"],"produced_object_ids":[],"errors":[],"blocked_reasons":[],"next_context":{}}
  from backend.discovery.market_discovery_runner import run_market_discovery
  out=run_market_discovery(workspace_id=ws,import_paths=p.get("import_paths",[]),parser_type_by_path=p.get("parser_type_by_path"),source_name_by_path=p.get("source_name_by_path"),import_only=True)
 elif name=="market_discovery":
  from backend.discovery.market_discovery_runner import run_market_discovery
  out=run_market_discovery(workspace_id=ws,dataset_paths=p.get("dataset_paths",[]),run_validation_services=False)
 elif name=="refinement_cycle":
  from backend.discovery.refinement_runner import run_refinement_cycle
  out=run_refinement_cycle(ws,refresh_pipeline=False)
 elif name=="acquisition_planning":out={"status":"completed","acquisition_plans":context.get("refinement_cycle",{}).get("acquisition_plans",[])}
 elif name=="opportunity_pipeline_refresh":
  from backend.discovery.opportunity_pipeline_builder import refresh_opportunity_pipeline
  out=refresh_opportunity_pipeline(ws)
 elif name=="source_calibration":
  from backend.discovery.source_calibration_engine import run_source_calibration
  out=run_source_calibration(ws).to_dict()
 elif name=="validation_sprint":
  from backend.discovery.validation_sprint_runner import run_validation_sprint
  out=run_validation_sprint(ws)
 elif name=="deliverable_package":
  from backend.deliverables.product_validation_sprint import build_product_validation_sprint_package
  out=build_product_validation_sprint_package(ws).to_dict()
 elif name=="executive_intelligence":
  from backend.intelligence.executive_command_runner import run_executive_intelligence_cycle
  out=run_executive_intelligence_cycle(ws)
 elif name=="portfolio_optimization":
  from backend.optimization.optimizer import build_portfolio_optimization_plan
  plan=build_portfolio_optimization_plan(ws)
  out={"status":"completed","optimization_plan":plan.to_dict(),"action_set_id":plan.action_set_id,"optimization_id":plan.optimization_id,"summary":plan.summary}
 elif name=="final_summary":out={"status":"completed","summary":"Workflow stages completed or were safely skipped."}
 else:return {"status":"blocked","output":{},"warnings":[],"errors":[],"blocked_reasons":["unsupported_stage"],"produced_object_ids":[],"next_context":{}}
 if not isinstance(out,dict):out={"status":"completed","output":str(out)}
 refs=[]
 for key,obj_type in (("discovery","discovery_run"),("snapshot","pipeline_snapshot"),("sprint","validation_sprint"),("portfolio_report","portfolio_report"),("brief","executive_brief"),("report","commercial_report"),("package","deliverable_package"),("opportunity_pipeline","pipeline"),("optimization_plan","optimization_plan")):
  x=out.get(key);x=x.get(key) if isinstance(x,dict) and key not in x and key=="discovery" else x
  if isinstance(x,dict):
   oid=next((x.get(k) for k in ("discovery_id","snapshot_id","sprint_id","portfolio_report_id","brief_id","report_id","package_id","optimization_id","action_set_id") if x.get(k)),None)
   if oid:refs.append({"object_type":obj_type,"object_id":oid,"registry":"marketos","relation":"produced"})
 return {"status":out.get("status","completed"),"output":out,"produced_object_ids":refs,"warnings":out.get("warnings",[]),"errors":out.get("errors",[]),"blocked_reasons":out.get("blocked_reasons",[]),"next_context":{name:out}}
