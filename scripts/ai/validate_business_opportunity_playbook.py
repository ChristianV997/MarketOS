"""scripts/ai/validate_business_opportunity_playbook.py -- deterministic,
offline operator validator for the business opportunity evaluation
playbook (docs/ai/BUSINESS_OPPORTUNITY_EVALUATION_PLAYBOOK.md) and its
synthetic fixtures (tests/fixtures/opportunity_playbook/*.json).

The playbook is a methodology, not a runtime authority: this validator
performs no scoring, ranking, economics calculation, or launch decision.
It only checks that the doc and its fixtures stay structurally honest
about the playbook's own rules -- schema shape, the five review modes,
the claim taxonomy, the eight evaluation lenses, fatal gates, the
missing-vs-explicit-zero boundary, prohibited claims/payloads, evidence-
class semantics, and the absence of scoring/ranking/launch authority.
No network I/O; nothing here writes to a fixture or the playbook doc.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from .operating_layer import ROOT, render_json_or_markdown, write_optional_output
except ImportError:  # pragma: no cover - direct script execution
    from operating_layer import ROOT, render_json_or_markdown, write_optional_output

DEFAULT_PLAYBOOK = ROOT / "docs" / "ai" / "BUSINESS_OPPORTUNITY_EVALUATION_PLAYBOOK.md"
DEFAULT_FIXTURES_DIR = ROOT / "tests" / "fixtures" / "opportunity_playbook"

OFFERING_KINDS = frozenset({"goods", "service", "digital_service", "physical_service", "hybrid", "unknown"})
ARCHETYPES = frozenset({
    "ecommerce_goods", "importation", "digital_products", "digital_services",
    "physical_services", "geographic_arbitrage", "client_idea", "evidence_discovered",
})
MODES = frozenset({"discover", "evaluate", "compare", "validate", "review-results"})
TAXONOMY = frozenset({"fact", "inference", "hypothesis", "unknown"})
EVALUATION_LENSES = frozenset({
    "reachable_buyer", "recurring_pain", "current_alternatives", "supply_gap",
    "evidence_quality", "unit_economics", "regulatory_risk", "geography",
})
EVIDENCE_CLASSES = frozenset({
    "fixture", "manual", "manual_import", "observed", "derived", "simulated",
    "planned", "live", "live_readonly", "unavailable",
})
LIVE_EVIDENCE_CLASSES = frozenset({"live", "live_readonly"})
DOC_EVIDENCE_CLASS_TERMS = EVIDENCE_CLASSES - {"unavailable"}  # "unavailable" is a state, not a class, in the doc's own prose
ALLOWED_STATUSES = frozenset({"blocked", "needs_evidence", "review_required", "planning_only"})
ALLOWED_FATAL_GATES = frozenset({
    "missing_or_negative_economics", "reachable_buyer_missing",
    "regulatory_status_unknown", "logistics_and_fx_missing", "distribution_missing",
})
ALLOWED_ECONOMICS_TOKENS = frozenset({
    "unknown", "missing", "not_applicable", "planning_assumption", "quoted_planning_input",
})
REQUIRED_FIXTURE_KEYS = frozenset({
    "scenario_id", "offering_kind", "opportunity_archetype", "candidate_id",
    "workspace_id", "geography", "language", "claims", "evidence", "economics",
    "blockers", "experiment", "expected",
})
REQUIRED_EXPERIMENT_KEYS = frozenset({"decision", "evidence_class", "stop_rule"})
FATAL_GATE_TABLE_ROW_COUNT = 11
NON_AUTHORITY_DOC_PHRASES = ("not a scorer", "not a ranker", "not a launch authority", "authority duplication")

FORBIDDEN_PAYLOAD_MARKERS = ("password=", "api_key=", "authorization:", "<html", "begin private key", "c:\\users\\")
FORBIDDEN_AUTHORITY_TOKENS = ("import ", "build_", "rank_", "score", "launch_authorized")
PROHIBITED_CLAIM_PHRASES = ("customers want", "the supplier is approved", "the margin is positive", "the market is legal")
_SECRET_PATH_RE = re.compile(r"(?:^|[\\/])(?:\.env|secrets?|credentials?)(?:$|[\\/])")
_NUMERIC_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


def _normalized(text: str) -> str:
    return " ".join(text.lower().split())


def _section(text: str, heading: str) -> str:
    match = re.search(rf"\n{re.escape(heading)}\n(.*?)(?:\n## |\Z)", "\n" + text, re.S)
    return match.group(1) if match else ""


def _is_nonzero_numeric(value: str) -> bool:
    return bool(_NUMERIC_RE.match(value)) and float(value) != 0.0


def validate_playbook_doc(path: Path) -> list[str]:
    """Structural checks distinct from tests/contracts/test_business_opportunity_playbook.py's
    substring coverage: this asserts closed-set equality (exact cardinality),
    not mere presence, for the modes, claim taxonomy, and evaluation lenses,
    so a silently added or removed mode/lens/taxonomy term is caught."""
    if not path.exists():
        return [f"playbook_missing: {path}"]
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []

    modes_body = _section(text, "## Review Modes")
    found_modes = {name.strip().lower() for name in re.findall(r"^### (.+)$", modes_body, re.M)}
    if found_modes != MODES:
        errors.append(f"modes_mismatch: expected {sorted(MODES)}, found {sorted(found_modes)}")

    taxonomy_body = _section(text, "## Claim Taxonomy")
    found_taxonomy = {term.lower() for term in re.findall(r"\*\*(\w+)\*\*", taxonomy_body)}
    if found_taxonomy != TAXONOMY:
        errors.append(f"claim_taxonomy_mismatch: expected {sorted(TAXONOMY)}, found {sorted(found_taxonomy)}")

    lenses_intro = _section(text, "## Evaluation Dimensions").split("\n### ", 1)[0]
    found_lenses = {token for token in re.findall(r"`([a-z_]+)`", lenses_intro)}
    if found_lenses != EVALUATION_LENSES:
        errors.append(f"evaluation_lenses_mismatch: expected {sorted(EVALUATION_LENSES)}, found {sorted(found_lenses)}")

    evidence_body = _section(text, "## Evidence Classes and States")
    found_evidence_terms = {token for token in re.findall(r"`([a-z_]+)`", evidence_body)}
    missing_evidence_terms = DOC_EVIDENCE_CLASS_TERMS - found_evidence_terms
    if missing_evidence_terms:
        errors.append(f"evidence_class_terms_missing: {sorted(missing_evidence_terms)}")

    gates_body = _section(text, "## Fatal Gates")
    gate_rows = [line for line in gates_body.splitlines() if line.startswith("|") and "---" not in line]
    data_rows = gate_rows[1:] if gate_rows else []  # first remaining row after the header is the header itself
    if len(data_rows) != FATAL_GATE_TABLE_ROW_COUNT:
        errors.append(f"fatal_gate_row_count: expected {FATAL_GATE_TABLE_ROW_COUNT}, found {len(data_rows)}")

    normalized = _normalized(text)
    missing_boundary_phrases = [phrase for phrase in NON_AUTHORITY_DOC_PHRASES if phrase not in normalized]
    if missing_boundary_phrases:
        errors.append(f"non_authority_boundary_missing: {missing_boundary_phrases}")

    return errors


def _scan_prohibited_text(raw: str) -> list[str]:
    lowered = raw.lower()
    errors: list[str] = []
    for marker in FORBIDDEN_PAYLOAD_MARKERS:
        if marker in lowered:
            errors.append(f"forbidden_payload_marker: {marker!r}")
    if "http://" in lowered or "https://" in lowered:
        errors.append("forbidden_live_url_reference")
    if _SECRET_PATH_RE.search(lowered):
        errors.append("forbidden_secret_path_reference")
    for token in FORBIDDEN_AUTHORITY_TOKENS:
        if token in lowered:
            errors.append(f"forbidden_authority_marker: {token!r}")
    if "launch_authorized" in raw:
        errors.append("forbidden_authority_marker: 'launch_authorized'")
    return errors


def validate_fixture(name: str, data: Any, raw: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return [f"{name}: fixture is not a JSON object"]

    missing_keys = REQUIRED_FIXTURE_KEYS - set(data.keys())
    if missing_keys:
        errors.append(f"{name}: missing keys {sorted(missing_keys)}")
        return errors  # remaining checks assume the base shape is present

    if data["scenario_id"] != name:
        errors.append(f"{name}: scenario_id {data['scenario_id']!r} does not match filename")
    if not str(data["candidate_id"]).startswith("fixture-candidate-"):
        errors.append(f"{name}: candidate_id {data['candidate_id']!r} lacks fixture identity prefix")
    if data["workspace_id"] != "fixture-workspace-methodology":
        errors.append(f"{name}: workspace_id {data['workspace_id']!r} is not the registered fixture workspace")
    if data["offering_kind"] not in OFFERING_KINDS:
        errors.append(f"{name}: offering_kind {data['offering_kind']!r} is not an allowed offering kind")
    if data.get("opportunity_archetype") not in ARCHETYPES:
        errors.append(f"{name}: opportunity_archetype {data.get('opportunity_archetype')!r} is not a covered archetype")

    for claim in data.get("claims", []):
        if claim.get("taxonomy") not in TAXONOMY:
            errors.append(f"{name}: claim {claim.get('id')} has invalid taxonomy {claim.get('taxonomy')!r}")
        if claim.get("evidence_class") not in EVIDENCE_CLASSES:
            errors.append(f"{name}: claim {claim.get('id')} has invalid evidence_class {claim.get('evidence_class')!r}")
        elif claim["evidence_class"] in LIVE_EVIDENCE_CLASSES:
            errors.append(f"{name}: claim {claim.get('id')} uses a live evidence_class in an offline fixture")
        if not str(claim.get("source_ref", "")).startswith("fixture://"):
            errors.append(f"{name}: claim {claim.get('id')} source_ref is not fixture-scoped")
        statement = str(claim.get("statement", "")).lower()
        for phrase in PROHIBITED_CLAIM_PHRASES:
            if phrase in statement:
                errors.append(f"{name}: claim {claim.get('id')} uses prohibited wording {phrase!r}")

    for evidence in data.get("evidence", []):
        if evidence.get("dimension") not in EVALUATION_LENSES:
            errors.append(f"{name}: evidence {evidence.get('id')} has invalid dimension {evidence.get('dimension')!r}")
        if evidence.get("evidence_class") not in EVIDENCE_CLASSES:
            errors.append(f"{name}: evidence {evidence.get('id')} has invalid evidence_class {evidence.get('evidence_class')!r}")
        elif evidence["evidence_class"] in LIVE_EVIDENCE_CLASSES:
            errors.append(f"{name}: evidence {evidence.get('id')} uses a live evidence_class in an offline fixture")
        if not str(evidence.get("source_ref", "")).startswith("fixture://"):
            errors.append(f"{name}: evidence {evidence.get('id')} source_ref is not fixture-scoped")

    economics = data.get("economics", {})
    for field_name, value in economics.items():
        if field_name == "currency":
            continue
        if value == 0 or value == "0":
            errors.append(f"{name}: economics.{field_name} is an explicit zero, not missing/unknown")
        elif isinstance(value, str) and value not in ALLOWED_ECONOMICS_TOKENS and not _is_nonzero_numeric(value):
            errors.append(f"{name}: economics.{field_name} uses an undocumented status token {value!r}")

    if not data.get("blockers"):
        errors.append(f"{name}: blockers must be non-empty")

    experiment = data.get("experiment", {})
    missing_experiment_keys = REQUIRED_EXPERIMENT_KEYS - set(experiment.keys())
    if missing_experiment_keys:
        errors.append(f"{name}: experiment missing keys {sorted(missing_experiment_keys)}")
    elif experiment.get("evidence_class") != "planned":
        errors.append(f"{name}: experiment.evidence_class must be 'planned', got {experiment.get('evidence_class')!r}")

    expected = data.get("expected", {})
    if expected.get("status") not in ALLOWED_STATUSES:
        errors.append(f"{name}: expected.status {expected.get('status')!r} is not an allowed status")
    if expected.get("fatal_gate") not in ALLOWED_FATAL_GATES:
        errors.append(f"{name}: expected.fatal_gate {expected.get('fatal_gate')!r} is not a recognized fatal gate")

    errors.extend(f"{name}: {issue}" for issue in _scan_prohibited_text(raw))
    return errors


def _stable_hash(playbook_text: str, fixtures: dict[str, Any]) -> str:
    payload = {
        "playbook_sha256": hashlib.sha256(playbook_text.encode("utf-8")).hexdigest(),
        "fixtures": {name: data for name, data in sorted(fixtures.items())},
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run_validation(playbook_path: Path = DEFAULT_PLAYBOOK, fixtures_dir: Path = DEFAULT_FIXTURES_DIR) -> dict[str, Any]:
    errors: list[str] = list(validate_playbook_doc(playbook_path))
    fixtures: dict[str, Any] = {}
    fixture_paths = sorted(fixtures_dir.glob("*.json")) if fixtures_dir.exists() else []
    if not fixture_paths:
        errors.append(f"no_fixtures_found: {fixtures_dir}")
    for fixture_path in fixture_paths:
        raw = fixture_path.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"{fixture_path.stem}: invalid JSON ({exc})")
            continue
        fixtures[fixture_path.stem] = data
        errors.extend(validate_fixture(fixture_path.stem, data, raw))

    playbook_text = playbook_path.read_text(encoding="utf-8") if playbook_path.exists() else ""
    return {
        "valid": not errors,
        "errors": errors,
        "playbook_path": str(playbook_path),
        "fixtures_dir": str(fixtures_dir),
        "fixture_count": len(fixtures),
        "fixture_names": sorted(fixtures),
        "stable_hash": _stable_hash(playbook_text, fixtures),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--playbook", type=Path, default=DEFAULT_PLAYBOOK, help="path to the playbook markdown file")
    parser.add_argument("--fixtures-dir", type=Path, default=DEFAULT_FIXTURES_DIR, help="path to the fixtures directory")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    if args.json and args.markdown:
        parser.error("choose --json or --markdown")

    result = run_validation(args.playbook, args.fixtures_dir)
    if args.json or args.markdown:
        content = render_json_or_markdown(result, markdown=args.markdown, title="MarketOS business opportunity playbook validation")
        write_optional_output(content, args.output)
        print(content, end="")
    else:
        print(f"Business Opportunity Playbook Validation: {'PASSED' if result['valid'] else 'FAILED'}")
        print(f"Fixtures checked: {result['fixture_count']} ({', '.join(result['fixture_names'])})")
        print(f"Stable hash: {result['stable_hash']}")
        if result["errors"]:
            print(f"Errors ({len(result['errors'])}):")
            for error in result["errors"]:
                print(f"  [X] {error}")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
