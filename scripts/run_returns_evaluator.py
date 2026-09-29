import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import argparse
import json
from typing import Any, Mapping

from backend.economics.kernel import EvidenceRef as EvidenceReference
from evaluation.commerce.reverse_logistics import evaluate_return_eligibility, ReturnEligibilityDecision

def _parse_evidence(raw_evidence: dict[str, Any]) -> Mapping[str, EvidenceReference | None]:
    parsed = {}
    for key, value in raw_evidence.items():
        if value is None:
            parsed[key] = None
        elif isinstance(value, dict) and "id" in value and "source" in value:
            parsed[key] = EvidenceReference(evidence_id=value["id"], source_type=value["source"])
        else:
            raise ValueError(f"malformed evidence reference for {key}")
    return parsed

def run_returns_evaluator(fixture_payload: str) -> dict[str, Any]:
    """Parse JSON payload and invoke the offline returns evaluator."""
    if len(fixture_payload) > 1024 * 100:  # 100KB limit
        return {"error": "input exceeds size limit"}

    try:
        data = json.loads(fixture_payload)
    except json.JSONDecodeError:
        return {"error": "malformed JSON input"}

    try:
        item_category = data["item_category"]
        days_since_delivery = int(data["days_since_delivery"])
        condition = data["condition"]
        evidence = _parse_evidence(data.get("evidence", {}))
    except (KeyError, ValueError) as e:
        return {"error": f"invalid input schema: {e}"}

    decision: ReturnEligibilityDecision = evaluate_return_eligibility(
        item_category=item_category,
        days_since_delivery=days_since_delivery,
        condition=condition,
        evidence=evidence,
    )

    return {
        "eligible": decision.eligible,
        "reason": decision.reason,
        "missing_evidence": decision.missing_evidence
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Offline Returns Eligibility Evaluator CLI")
    parser.add_argument("--fixture-path", type=str, required=True, help="Path to JSON file of the returns context")
    args = parser.parse_args()

    with open(args.fixture_path, "r") as f:
        payload = f.read()
    result = run_returns_evaluator(payload)
    print(json.dumps(result, indent=2))
