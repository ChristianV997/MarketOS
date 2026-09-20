#!/usr/bin/env python3
"""Bounded operator-manifest vertical for PR #283.

Consumes #279's real CLI (--manifest, --candidate-id, --scenario-template,
--confirm-supplier-document) and the existing TrustOS export construction
from scripts/run_operator_dogfood_workflow.py. Does not reimplement replay,
research-to-decision, compliance scoring, or a second catalog.

Fixture / manual / dry-run output never yields live_validated,
evidence_state=present, or launch authorization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_operator_dogfood_workflow as bridge

SCHEMA = "MarketOS.OperatorDogfoodVertical.v1"
MANIFEST_SCHEMA = "MarketOS.OperatorDogfoodManifest.v1"
MAX_MANIFEST_BYTES = 256 * 1024
MAX_CANDIDATES = 32
MAX_CONFIRMATIONS = 16
CANONICAL_TEMPLATES = (
    "hydroponics_positive_candidate",
    "smart_pet_support_burden_candidate",
    "solar_4g_security_blocked_candidate",
    "commodity_electronics_rejected_candidate",
    "high_ticket_deferred_candidate",
)
FORBIDDEN_EVIDENCE = frozenset({"present", "passed", "live_validated", "verified_live", "actual"})
FORBIDDEN_STATUS_TOKENS = ("live_validated", "verified_live", "production", "launch_authorized")
SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|authorization|password|secret|bearer\s+\S+|sk-(?:live|proj)-[A-Za-z0-9]+|ghp_[A-Za-z0-9]+)"
)
STALE_REQUIRED_KEYS = ("captured_at", "candidates")


class VerticalError(Exception):
    def __init__(self, reason: str, classification: str = "malformed") -> None:
        super().__init__(reason)
        self.reason = reason
        self.classification = classification


def _fingerprint(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _contains_secret(value: Any) -> bool:
    if isinstance(value, str):
        return bool(SECRET_RE.search(value))
    if isinstance(value, Mapping):
        return any(_contains_secret(k) or _contains_secret(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_secret(item) for item in value)
    return False


def _resolve_under_repo(repo: Path, raw: Path) -> Path:
    path = raw if raw.is_absolute() else (repo / raw)
    resolved = path.resolve()
    repo_resolved = repo.resolve()
    if repo_resolved not in resolved.parents and resolved != repo_resolved:
        raise VerticalError("manifest_path_outside_repo", "blocked")
    return resolved


def load_operator_manifest(repo: Path, manifest_path: Path) -> dict[str, Any]:
    resolved = _resolve_under_repo(repo, manifest_path)
    if not resolved.is_file():
        raise VerticalError("manifest_absent", "unavailable")
    size = resolved.stat().st_size
    if size <= 0:
        raise VerticalError("manifest_empty", "malformed")
    if size > MAX_MANIFEST_BYTES:
        raise VerticalError("manifest_exceeds_bound", "malformed")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerticalError(f"manifest_invalid_json:{type(exc).__name__}", "malformed") from exc
    if not isinstance(payload, dict):
        raise VerticalError("manifest_root_must_be_object", "malformed")
    if _contains_secret(payload):
        raise VerticalError("manifest_secret_shaped", "blocked")
    missing = [key for key in STALE_REQUIRED_KEYS if key not in payload]
    if missing:
        raise VerticalError(f"manifest_stale_missing:{','.join(missing)}", "blocked")
    captured = payload.get("captured_at")
    if not isinstance(captured, str) or not captured.strip():
        raise VerticalError("manifest_stale_captured_at", "blocked")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise VerticalError("manifest_candidates_required", "malformed")
    if len(candidates) > MAX_CANDIDATES:
        raise VerticalError("manifest_candidate_bound", "malformed")
    ids: list[str] = []
    for row in candidates:
        if not isinstance(row, dict):
            raise VerticalError("manifest_candidate_not_object", "malformed")
        candidate_id = row.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise VerticalError("manifest_candidate_id_required", "malformed")
        ids.append(candidate_id.strip())
    if len(set(ids)) != len(ids):
        raise VerticalError("manifest_duplicate_candidate_id", "malformed")
    payload["_resolved_path"] = str(resolved)
    payload["_candidate_ids"] = ids
    return payload


def normalize_confirmations(values: Sequence[Sequence[str]] | None) -> tuple[tuple[str, str, str], ...]:
    if not values:
        return ()
    if len(values) > MAX_CONFIRMATIONS:
        raise VerticalError("confirmation_bound", "malformed")
    seen: set[tuple[str, str, str]] = set()
    out: list[tuple[str, str, str]] = []
    for item in values:
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            raise VerticalError("confirmation_requires_offer_sku_reference", "malformed")
        offer, sku, reference = (str(part).strip() for part in item)
        if not offer or not sku or not reference:
            raise VerticalError("confirmation_fields_required", "malformed")
        key = (offer, sku, reference)
        if key in seen:
            raise VerticalError("duplicate_confirmation", "malformed")
        seen.add(key)
        out.append(key)
    return tuple(out)


def select_candidate(manifest: Mapping[str, Any], candidate_id: str | None) -> str:
    ids = list(manifest.get("_candidate_ids") or [])
    if candidate_id is None:
        if len(ids) != 1:
            raise VerticalError("candidate_id_required_when_ambiguous", "malformed")
        return ids[0]
    wanted = candidate_id.strip()
    if wanted not in ids:
        raise VerticalError("unknown_candidate_id", "blocked")
    return wanted


def select_template(name: str | None) -> str:
    if not name:
        raise VerticalError("scenario_template_required", "malformed")
    if name not in CANONICAL_TEMPLATES:
        raise VerticalError("unknown_scenario_template", "blocked")
    return name


def confirmations_match_offers(
    manifest: Mapping[str, Any],
    confirmations: tuple[tuple[str, str, str], ...],
    *,
    require_match: bool,
) -> None:
    if not require_match or not confirmations:
        return
    blob = json.dumps(manifest, sort_keys=True, default=str)
    for offer, sku, reference in confirmations:
        if offer not in blob or sku not in blob or reference not in blob:
            raise VerticalError("supplier_confirmation_mismatch", "blocked")


def invoke_replay(
    repo: Path,
    *,
    manifest_path: Path,
    candidate_id: str,
    template: str,
    confirmations: tuple[tuple[str, str, str], ...],
    runner=None,
) -> dict[str, Any]:
    argv = [
        sys.executable,
        "scripts/run_commercial_replay_integration.py",
        "--json",
        "--manifest",
        str(manifest_path),
        "--candidate-id",
        candidate_id,
        "--scenario-template",
        template,
    ]
    for offer, sku, reference in confirmations:
        argv.extend(["--confirm-supplier-document", offer, sku, reference])
    run = runner or bridge._run
    result = run(argv, cwd=repo, timeout_s=180.0)
    if not result.get("ok"):
        return bridge._phase(
            "commercial_dry_run",
            "malformed" if result.get("reason") == "stdout_not_json" else "unavailable",
            {"reason": result.get("reason"), "candidate_id": candidate_id, "template": template},
        )
    document = result["json"] or {}
    scenarios = document.get("scenarios") or {}
    rows = scenarios.get("rows") or document.get("rows") or []
    if scenarios.get("result") == "unavailable":
        return bridge._phase("commercial_dry_run", "unavailable", {"reason": scenarios.get("reason", "scenarios_unavailable"), "candidate_id": candidate_id})
    replay_clean = True
    if rows:
        replay_clean = all(row.get("replay_equal", True) for row in rows)
    if rows and not replay_clean:
        return bridge._phase(
            "commercial_dry_run",
            "blocked",
            {"reason": "replay_mismatch", "candidate_id": candidate_id, "row_count": len(rows)},
        )
    if not rows and scenarios.get("result") not in {None, "actual"}:
        return bridge._phase("commercial_dry_run", "unavailable", {"reason": "no_replay_rows", "candidate_id": candidate_id})
    summary_rows = []
    for row in rows or [
        {
            "scenario": template,
            "candidate_id": candidate_id,
            "achievable_stage": (document.get("commerce") or {}).get("achievable_stage"),
            "promoted_to_launch": False,
            "blockers": ["operator_vertical_dry_run"],
            "evidence_classes": document.get("evidence_classes") or {},
        }
    ]:
        evidence_classes = row.get("evidence_classes") or document.get("evidence_classes") or {}
        economics = evidence_classes.get("economics")
        compliance = evidence_classes.get("compliance")
        summary_rows.append(
            {
                "scenario": row.get("scenario") or template,
                "candidate_id": row.get("candidate_id") or candidate_id,
                "achievable_stage": row.get("achievable_stage"),
                "promoted_to_launch": bool(row.get("promoted_to_launch")),
                "blockers": list(row.get("blockers") or ["operator_vertical_dry_run"]),
                "evidence_classes": evidence_classes,
                "economics_evidence": economics,
                "compliance_evidence": compliance,
                "missing_cost_inputs": list(row.get("missing_cost_inputs") or []),
            }
        )
    return bridge._phase(
        "commercial_dry_run",
        "passed",
        {"row_count": len(summary_rows), "rows": summary_rows, "candidate_id": candidate_id, "template": template},
    )


def _forbid_live_claims(payload: Mapping[str, Any]) -> list[str]:
    issues: set[str] = set()

    def inspect(value: Any) -> None:
        if isinstance(value, Mapping):
            evidence_state = value.get("evidence_state")
            if isinstance(evidence_state, str) and evidence_state.casefold() in FORBIDDEN_EVIDENCE:
                issues.add("forbidden_evidence_state")
            status = value.get("status")
            if isinstance(status, str) and any(
                token in status.casefold() for token in FORBIDDEN_STATUS_TOKENS
            ):
                issues.add("forbidden_status_token")
            # The key itself is not a claim: this bridge deliberately emits
            # live_validated=false and launch_authorized=false. Only a value
            # other than the explicit boolean False is unsafe/ambiguous.
            if "live_validated" in value and value["live_validated"] is not False:
                issues.add("live_validated_claim")
            if "launch_authorized" in value and value["launch_authorized"] is not False:
                issues.add("launch_authorization")
            for nested in value.values():
                inspect(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                inspect(nested)

    inspect(payload)
    return sorted(issues)


def export_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    phase = bridge.trustos_export(rows)
    if phase["classification"] != "passed":
        return phase
    sanitized_exports = []
    blocked = []
    for item in phase["detail"].get("exports", []):
        payload = dict(item.get("payload") or {})
        payload["evidence_state"] = "requires_review"
        payload["launch_authorized"] = False
        payload["live_validated"] = False
        payload.setdefault("status", "fixture_dry_run_requires_review")
        issues = _forbid_live_claims({**item, **payload, "evidence_state": item.get("evidence_state", payload["evidence_state"])})
        if item.get("evidence_state") in FORBIDDEN_EVIDENCE:
            issues.append("upstream_evidence_state_forbidden")
        if issues:
            blocked.append({"candidate_id": payload.get("workspace_id"), "issues": issues})
            continue
        item = dict(item)
        item["payload"] = payload
        item["evidence_state"] = "requires_review"
        sanitized_exports.append(item)
    if blocked:
        return bridge._phase("trustos_export", "blocked", {"reason": "export_claim_rejected", "blocked": blocked})
    phase["detail"]["exports"] = sanitized_exports
    return phase


def run_vertical(
    repo: Path,
    *,
    manifest_path: Path,
    candidate_id: str | None,
    scenario_template: str | None,
    confirmations: Sequence[Sequence[str]] | None = None,
    require_confirmation_match: bool = True,
    runner=None,
) -> dict[str, Any]:
    phases: list[dict[str, Any]] = []
    try:
        manifest = load_operator_manifest(repo, manifest_path)
        selected = select_candidate(manifest, candidate_id)
        template = select_template(scenario_template)
        confirmed = normalize_confirmations(confirmations)
        confirmations_match_offers(manifest, confirmed, require_match=require_confirmation_match)
    except VerticalError as exc:
        phases.append(bridge._phase("manifest_intake", exc.classification, {"reason": exc.reason}))
        report = bridge.sanitized_handoff(repo, phases)
        report["schema"] = SCHEMA
        report["mode"] = "operator_vertical"
        report["live_validated"] = False
        report["launch_authorized"] = False
        return report

    phases.append(
        bridge._phase(
            "manifest_intake",
            "passed",
            {
                "candidate_id": selected,
                "template": template,
                "confirmation_count": len(confirmed),
                "manifest_fingerprint": _fingerprint({k: v for k, v in manifest.items() if not str(k).startswith("_")}),
            },
        )
    )
    dry = invoke_replay(
        repo,
        manifest_path=Path(manifest["_resolved_path"]),
        candidate_id=selected,
        template=template,
        confirmations=confirmed,
        runner=runner,
    )
    phases.append(dry)
    if dry["classification"] != "passed":
        phases.append(bridge._phase("trustos_export", "not_run", {"reason": f"commercial_dry_run_{dry['classification']}"}))
        report = bridge.sanitized_handoff(repo, phases)
        report["schema"] = SCHEMA
        report["mode"] = "operator_vertical"
        report["live_validated"] = False
        report["launch_authorized"] = False
        return report
    phases.append(export_rows(dry["detail"].get("rows") or []))
    report = bridge.sanitized_handoff(repo, phases)
    report["schema"] = SCHEMA
    report["mode"] = "operator_vertical"
    report["live_validated"] = False
    report["launch_authorized"] = False
    report["candidate_id"] = selected
    report["scenario_template"] = template
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--candidate-id")
    parser.add_argument("--scenario-template", choices=CANONICAL_TEMPLATES)
    parser.add_argument(
        "--confirm-supplier-document",
        action="append",
        nargs=3,
        default=[],
        metavar=("OFFER_ID", "EXACT_SKU", "REFERENCE"),
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_vertical(
        args.repo.resolve(),
        manifest_path=args.manifest,
        candidate_id=args.candidate_id,
        scenario_template=args.scenario_template,
        confirmations=args.confirm_supplier_document,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("overall_classification") in {"passed", "not_run", "ci_unavailable"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
