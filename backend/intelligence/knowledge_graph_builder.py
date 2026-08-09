from __future__ import annotations
import uuid,time
from .knowledge_graph import KnowledgeNode,KnowledgeEdge,KnowledgeGraphSnapshot
from .knowledge_registry import get_knowledge_registry
def _node(kind,obj,workspace,registry):
 d=obj.to_dict() if hasattr(obj,"to_dict") else obj; oid=next((d.get(x) for x in ("evidence_id","import_id","analysis_id","plan_id","profile_id","opportunity_id","scorecard_id","sprint_id","report_id","portfolio_report_id","package_id","discovery_id","hypothesis_run_id") if d.get(x)),""); title=d.get("name") or d.get("title") or d.get("opportunity_name") or oid; return KnowledgeNode("knowledge_"+uuid.uuid5(uuid.NAMESPACE_URL,f"{workspace}:{kind}:{oid}").hex[:16],kind,str(title),str(d.get("summary") or d.get("objective") or ""),workspace,oid,registry,float(d.get("score",d.get("validation_score",0)) or 0),float(d.get("confidence",0) or 0),str(d.get("status",d.get("stage",""))),list(d.get("tags",[])),d.get("created_at",time.time()),d.get("updated_at",d.get("created_at",time.time())),d)
def build_knowledge_graph_snapshot(workspace_id="default",include_evidence=True,include_reports=True,include_deliverables=True,limit_per_type=200):
 r=get_knowledge_registry();nodes=[];warnings=[]
 def add(kind,items,reg):
  for x in list(items)[:limit_per_type]:nodes.append(_node(kind,x,workspace_id,reg))
 try:
  from backend.discovery.discovery_registry import get_discovery_registry
  dr=get_discovery_registry(); add("evidence_record",dr.list_evidence(workspace_id=workspace_id,limit=limit_per_type) if include_evidence else [],"discovery_registry");add("discovery_run",dr.list_category_discoveries(workspace_id,limit=limit_per_type),"discovery_registry");add("product_hypothesis",[h for run in dr.list_product_hypothesis_runs(workspace_id,limit=limit_per_type) for h in run.hypotheses],"discovery_registry")
  from backend.discovery.refinement_registry import get_refinement_registry
  rr=get_refinement_registry();add("evidence_gap",[g for a in rr.list_gap_analyses(workspace_id,limit_per_type) for g in a.gaps],"refinement_registry");add("import_recommendation",[x for p in rr.list_import_plans(workspace_id,limit_per_type) for x in p.recommendations],"refinement_registry")
  from backend.discovery.opportunity_registry import get_opportunity_registry
  orr=get_opportunity_registry();add("opportunity",orr.list_opportunities(workspace_id,limit=limit_per_type),"opportunity_registry");add("pipeline_snapshot",orr.list_snapshots(workspace_id,limit_per_type),"opportunity_registry")
  from backend.discovery.validation_sprint_registry import get_validation_sprint_registry
  vs=get_validation_sprint_registry();add("validation_sprint",vs.list_sprints(workspace_id,limit=limit_per_type),"validation_registry");add("validation_scorecard",vs.list_scorecards(workspace_id,limit=limit_per_type),"validation_registry")
  if include_reports:
   from backend.organization.report_registry import get_report_registry
   add("commercial_report",get_report_registry().list_reports(workspace_id,limit=limit_per_type),"report_registry");add("portfolio_report",get_report_registry().list_portfolio_reports(workspace_id,limit=limit_per_type),"report_registry")
  if include_deliverables:
   from backend.deliverables.registry import get_deliverable_registry
   add("deliverable_package",get_deliverable_registry().list_packages(workspace_id,limit=limit_per_type),"deliverable_registry")
 except Exception as exc:warnings.append(f"registry_load_warning:{type(exc).__name__}")
 edges=[]; by_source={n.source_object_id:n for n in nodes}
 def edge(a,b,rel,reason):
  if a and b and a.node_id!=b.node_id:edges.append(KnowledgeEdge("edge_"+uuid.uuid5(uuid.NAMESPACE_URL,f"{a.node_id}:{b.node_id}:{rel}").hex[:16],a.node_id,b.node_id,rel,.8,.8,[reason],{"method":"exact_persisted_id_match","real_market_claims":False}))
 for n in nodes:
  d=n.metadata
  for eid in d.get("evidence_ids",[]):edge(by_source.get(eid),n,"supports","Evidence ID is explicitly linked by the source object.")
  for gid in d.get("gap_ids",[]):edge(by_source.get(gid),n,"blocks","Gap ID is explicitly linked by the source object.")
  for rid in d.get("report_ids",[]):edge(by_source.get(rid),n,"reports_on","Report ID is explicitly linked by the source object.")
  if d.get("opportunity_id"):edge(by_source.get(d["opportunity_id"]),n,"validates" if n.node_type=="validation_scorecard" else "reports_on","Opportunity ID is explicitly linked.")
 types={};rels={};connected={x.from_node_id for x in edges}|{x.to_node_id for x in edges}
 for n in nodes:types[n.node_type]=types.get(n.node_type,0)+1
 for e in edges:rels[e.relation_type]=rels.get(e.relation_type,0)+1
 snap=KnowledgeGraphSnapshot("graph_"+uuid.uuid4().hex[:16],workspace_id,"Executive Knowledge Graph",len(nodes),len(edges),types,rels,[x.to_dict() for x in sorted(nodes,key=lambda x:(-x.score,x.title))[:20]],[x.to_dict() for x in nodes if x.node_id not in connected][:20],[],metadata={"warnings":warnings,"deterministic":True});r.register_nodes(nodes);r.register_edges(edges);r.register_snapshot(snap);return {"snapshot":snap.to_dict(),"nodes_added":len(nodes),"edges_added":len(edges),"warnings":warnings,"status":"completed"}
