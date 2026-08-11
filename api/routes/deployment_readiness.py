from fastapi import APIRouter, Request
from backend.deployment.readiness import build_readiness
from backend.security.rate_limit import check_rate_limit, event_read_policy
from fastapi.responses import JSONResponse
router=APIRouter(prefix="/api/deployment",tags=["deployment-readiness"])
@router.get("/readiness")
def readiness(request: Request=None):
 d=check_rate_limit(event_read_policy(),getattr(getattr(request,"client",None),"host",None) or "direct")
 if not d.allowed:return JSONResponse({"status":"rate_limited","read_only":True,"mutated":False},status_code=429)
 return build_readiness().to_dict()
