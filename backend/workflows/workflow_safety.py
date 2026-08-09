from copy import deepcopy
def validate_workflow_payload_safe(payload):
 p=deepcopy(payload or {});blocked=[];warnings=[];bad={"live","confirm_live","live_action_requested","execute_live","mutate","publish","send_message","place_order","order","pay","payment","spend","launch"}
 def scan(x,path=""):
  if isinstance(x,dict):
   for k,v in x.items():
    key=str(k).lower()
    if key in bad and bool(v):blocked.append(f"unsafe_flag:{path+key}")
    if key in {"url","endpoint"} and isinstance(v,str) and v.startswith(("http://","https://")):blocked.append(f"external_url:{path+key}")
    scan(v,path+key+".")
  elif isinstance(x,list):
   if len(x)>100:blocked.append(f"list_limit:{path}")
   for i,v in enumerate(x):scan(v,path+str(i)+".")
 scan(p);return {"safe":not blocked,"blocked_reasons":sorted(set(blocked)),"warnings":warnings,"sanitized_payload":p}
