from __future__ import annotations
import re
from typing import Any

_BLOCKED = {"guarantee": "guaranteed outcome", "guaranteed": "guaranteed outcome", "roi": "ROI claim", "roas": "ROAS claim", "profit": "profit claim", "conversion": "conversion claim", "clinically proven": "medical substantiation claim", "cure": "medical treatment claim", "treat": "medical treatment claim", "limited time": "false scarcity risk", "only today": "false urgency risk", "testimonial": "testimonial requires verified permissioned evidence", "review": "review claim requires verified evidence", "before and after": "deceptive before/after risk", "certified": "certification requires evidence"}
_CAUTION = {"best": "comparative claim requires evidence", "#1": "ranking claim requires evidence", "proven": "proof claim requires evidence", "viral": "performance claim requires evidence", "made in": "origin claim requires evidence", "non-toxic": "safety/material claim requires evidence"}

def detect_prohibited_claims(text: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    value = str(text or ""); lower = value.lower(); blocked = [why for term, why in _BLOCKED.items() if term in lower]; caution = [why for term, why in _CAUTION.items() if term in lower]
    return {"status": "blocked" if blocked else "caution" if caution else "safe", "blocked_reasons": blocked + caution, "required_evidence": ["direct, permissioned, product-specific substantiation" for _ in blocked + caution], "limitations": ["Creative copy is a draft and must be reviewed before any use."]}

def validate_claim_substantiation(claim: str, evidence_basis: list[dict[str, Any]], product_report: Any | None = None, market_report: Any | None = None) -> dict[str, Any]:
    result = detect_prohibited_claims(claim)
    if result["status"] == "safe" and not evidence_basis: result.update(status="caution", blocked_reasons=["claim has no linked evidence"], required_evidence=["product-specific supporting evidence"])
    return result

def sanitize_creative_claim(claim: str, evidence_basis: list[dict[str, Any]], context: dict[str, Any] | None = None) -> dict[str, Any]:
    result = validate_claim_substantiation(claim, evidence_basis)
    if result["status"] == "blocked": result["safe_text"] = "Draft hypothesis: explore whether this product may fit the stated use case; substantiate before use."
    elif result["status"] == "caution": result["safe_text"] = f"Draft hypothesis: {str(claim).rstrip('.')} (validate before use)."
    else: result["safe_text"] = str(claim)
    return result
