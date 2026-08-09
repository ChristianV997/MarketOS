from __future__ import annotations
import json,os,threading
from pathlib import Path
from .knowledge_graph import KnowledgeNode,KnowledgeEdge,KnowledgeGraphSnapshot
class KnowledgeRegistry:
 def __init__(self,path=None):self.path=Path(path or os.getenv("MARKETOS_KNOWLEDGE_GRAPH_STATE","state/knowledge_graph_registry.json"));self.nodes={};self.edges={};self.snapshots={};self.load()
 def register_node(self,x):self.nodes[x.node_id]=x;self.save();return x
 def register_nodes(self,xs):
  for x in xs:self.nodes[x.node_id]=x
  self.save();return xs
 def get_node(self,x):return self.nodes.get(x)
 def list_nodes(self,workspace_id=None,node_type=None,status=None,tag=None,limit=200):return [x for x in self.nodes.values() if (workspace_id is None or x.workspace_id==workspace_id) and (node_type is None or x.node_type==node_type) and (status is None or x.status==status) and (tag is None or tag in x.tags)][:max(0,min(int(limit),2000))]
 def register_edge(self,x):self.edges[x.edge_id]=x;self.save();return x
 def register_edges(self,xs):
  for x in xs:self.edges[x.edge_id]=x
  self.save();return xs
 def get_edge(self,x):return self.edges.get(x)
 def list_edges(self,workspace_id=None,from_node_id=None,to_node_id=None,relation_type=None,limit=500):
  allowed=None if workspace_id is None else {x.node_id for x in self.nodes.values() if x.workspace_id==workspace_id};return [x for x in self.edges.values() if (allowed is None or x.from_node_id in allowed or x.to_node_id in allowed) and (from_node_id is None or x.from_node_id==from_node_id) and (to_node_id is None or x.to_node_id==to_node_id) and (relation_type is None or x.relation_type==relation_type)][:max(0,min(int(limit),5000))]
 def neighbors(self,node_id,relation_type=None,direction="both",limit=100):
  xs=[x for x in self.edges.values() if (direction in {"both","out"} and x.from_node_id==node_id or direction in {"both","in"} and x.to_node_id==node_id) and (relation_type is None or x.relation_type==relation_type)]; ids=[]
  for x in xs:
   other=x.to_node_id if x.from_node_id==node_id else x.from_node_id
   if other not in ids:ids.append(other)
  return [self.nodes[x] for x in ids[:max(0,min(int(limit),500))] if x in self.nodes]
 def register_snapshot(self,x):self.snapshots[x.snapshot_id]=x;self.save();return x
 def get_snapshot(self,x):return self.snapshots.get(x)
 def list_snapshots(self,workspace_id=None,limit=50):return sorted([x for x in self.snapshots.values() if workspace_id is None or x.workspace_id==workspace_id],key=lambda x:x.created_at,reverse=True)[:max(0,min(int(limit),500))]
 def latest_snapshot(self,workspace_id=None):
  xs=self.list_snapshots(workspace_id,1);return xs[0] if xs else None
 def clear_for_tests(self):self.nodes.clear();self.edges.clear();self.snapshots.clear();self.save()
 def to_dict(self):return {"nodes":{k:v.to_dict() for k,v in self.nodes.items()},"edges":{k:v.to_dict() for k,v in self.edges.items()},"snapshots":{k:v.to_dict() for k,v in self.snapshots.items()}}
 def load(self):
  try:
   if self.path.exists():
    d=json.loads(self.path.read_text(encoding="utf-8"));self.nodes={k:KnowledgeNode.from_dict(v) for k,v in d.get("nodes",{}).items()};self.edges={k:KnowledgeEdge.from_dict(v) for k,v in d.get("edges",{}).items()};self.snapshots={k:KnowledgeGraphSnapshot.from_dict(v) for k,v in d.get("snapshots",{}).items()}
  except Exception:self.nodes,self.edges,self.snapshots={},{},{}
 def save(self):
  try:self.path.parent.mkdir(parents=True,exist_ok=True);t=self.path.with_suffix(".tmp");t.write_text(json.dumps(self.to_dict(),indent=2,default=str),encoding="utf-8");t.replace(self.path)
  except Exception:pass
_singleton=None;_lock=threading.Lock()
def get_knowledge_registry():
 global _singleton
 if _singleton is None:
  with _lock:
   if _singleton is None:_singleton=KnowledgeRegistry()
 return _singleton
