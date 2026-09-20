"""scripts/ai/validate_source_adaptation_registry.py -- CLI validator and reporting
utility for MarketOS source adaptation governance.

Supports:
- Registry schema and policy validation fail-closed
- Structured JSON output with sanitized metadata
- Aggregate summary breakdown (accepted, rejected, deferred, emulated)
- Deterministic stable SHA256 content hash
- 100% offline, zero network execution
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List

# Ensure repo root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evaluation.source_governance.registry import (
    SourceAdaptationRegistry,
    WorkOrderRegistry,
    redact_secrets,
)
from evaluation.source_governance.validator import (
    generate_evidence_bundle,
    validate_registry,
    validate_source_work_order_correspondence,
    validate_target_boundary_collisions,
    validate_work_order,
)


def run_validation(registry_path: Path, max_freshness_days: int = 180) -> Dict[str, Any]:
    """Execute offline validation against source adaptation registry."""
    if not registry_path.exists():
        return {
            "valid": False,
            "errors": [f"Registry file not found: {registry_path}"],
            "total_sources": 0,
            "summary": {},
            "stable_hash": "",
        }

    try:
        registry = SourceAdaptationRegistry.load_from_file(registry_path)
    except Exception as e:
        return {
            "valid": False,
            "errors": [f"Failed to load registry: {e}"],
            "total_sources": 0,
            "summary": {},
            "stable_hash": "",
        }

    errors = validate_registry(registry)
    summary = registry.summarize()
    stable_hash = registry.compute_stable_hash()

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "total_sources": len(registry.records),
        "summary": summary,
        "stable_hash": stable_hash,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="MarketOS Source Adaptation Registry Validator and Governance CLI"
    )
    parser.add_argument(
        "--registry",
        type=str,
        default="data/source_adaptation_registry.json",
        help="Path to source_adaptation_registry.json",
    )
    parser.add_argument(
        "--work-orders",
        nargs="?",
        const="data/source_adaptation_work_orders.json",
        default=None,
        help="Validate work orders file (default: data/source_adaptation_work_orders.json when specified without value)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List registered sources and their adaptation modes/statuses",
    )
    parser.add_argument(
        "--filter-mode",
        type=str,
        default=None,
        help="Filter listed sources or work orders by adaptation mode (copy_pattern, emulate, reference_only, defer, reject)",
    )
    parser.add_argument(
        "--bundle",
        type=str,
        default=None,
        help="Generate review evidence bundle for specified source_id",
    )
    parser.add_argument(
        "--check-collisions",
        action="store_true",
        help="Check active work orders for target boundary collisions",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit full report as JSON to stdout",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print tabular summary of sources, modes, and statuses",
    )
    parser.add_argument(
        "--hash",
        action="store_true",
        help="Output the stable SHA-256 hash of the registry",
    )
    parser.add_argument(
        "--max-freshness-days",
        type=int,
        default=180,
        help="Maximum allowed age of last reviewed timestamp in days (default: 180)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress non-error stdout; return exit code only",
    )

    args = parser.parse_args()
    reg_path = Path(args.registry).resolve()

    # Load registry if needed
    registry: SourceAdaptationRegistry | None = None
    if reg_path.exists():
        try:
            registry = SourceAdaptationRegistry.load_from_file(reg_path)
        except Exception:
            registry = None

    # Handle --bundle <source_id>
    if args.bundle:
        wo_path = Path(args.work_orders or "data/source_adaptation_work_orders.json").resolve()
        if not wo_path.exists():
            print(f"Error: Work orders file not found: {wo_path}", file=sys.stderr)
            return 1
        wo_registry = WorkOrderRegistry.load_from_file(wo_path)
        matching_wo = None
        for wo in wo_registry.work_orders.values():
            if wo.source_id == args.bundle or wo.work_order_id == args.bundle:
                matching_wo = wo
                break
        if not matching_wo:
            print(f"Error: No work order found for source '{args.bundle}'", file=sys.stderr)
            return 1
        matching_rec = registry.get_record(matching_wo.source_id) if registry else None
        bundle = generate_evidence_bundle(matching_wo, matching_rec)
        if args.json:
            print(json.dumps(bundle.to_dict(), indent=2))
        else:
            print(bundle.render_markdown())
        return 0

    # Handle --list
    if args.list:
        if not registry:
            print(f"Error: Registry not found at {reg_path}", file=sys.stderr)
            return 1
        records = list(registry.records.values())
        if args.filter_mode:
            records = [r for r in records if r.adaptation_mode == args.filter_mode]
        records = sorted(records, key=lambda r: r.source_id)
        if args.json:
            print(json.dumps([redact_secrets(r.to_dict()) for r in records], indent=2))
        else:
            print(f"{'Source ID':<36} {'Mode':<16} {'Status':<20} {'Target Authority'}")
            print("-" * 100)
            for r in records:
                print(f"{r.source_id:<36} {r.adaptation_mode:<16} {r.integration_status:<20} {r.marketos_target_authority}")
            print("-" * 100)
            print(f"Total: {len(records)} sources")
        return 0

    # Handle --check-collisions
    if args.check_collisions:
        wo_path = Path(args.work_orders or "data/source_adaptation_work_orders.json").resolve()
        if not wo_path.exists():
            print(f"Error: Work orders file not found: {wo_path}", file=sys.stderr)
            return 1
        wo_registry = WorkOrderRegistry.load_from_file(wo_path)
        collisions = validate_target_boundary_collisions(list(wo_registry.work_orders.values()))
        if args.json:
            print(json.dumps({"collisions": collisions, "valid": len(collisions) == 0}, indent=2))
        else:
            if collisions:
                print("Target Boundary Collisions Detected:")
                for c in collisions:
                    print(f"  [X] {c}")
                return 1
            else:
                print("No target boundary collisions detected across active work orders.")
        return 0 if len(collisions) == 0 else 1

    # Handle --work-orders validation
    if args.work_orders is not None:
        wo_path = Path(args.work_orders).resolve()
        if not wo_path.exists():
            print(f"Error: Work orders file not found: {wo_path}", file=sys.stderr)
            return 1
        wo_registry = WorkOrderRegistry.load_from_file(wo_path)
        wo_errors: List[str] = []
        for wo in wo_registry.work_orders.values():
            wo_errors.extend(validate_work_order(wo))
        wo_errors.extend(validate_target_boundary_collisions(list(wo_registry.work_orders.values())))
        if registry is not None:
            wo_errors.extend(
                validate_source_work_order_correspondence(
                    registry, list(wo_registry.work_orders.values())
                )
            )
        is_wo_valid = len(wo_errors) == 0
        wo_res = {
            "valid": is_wo_valid,
            "total_work_orders": len(wo_registry.work_orders),
            "errors": wo_errors,
            "stable_hash": wo_registry.compute_stable_hash(),
        }
        if args.json:
            print(json.dumps(wo_res, indent=2))
        else:
            print("=" * 70)
            print("MarketOS Source Adaptation Work Orders Validation")
            print("=" * 70)
            print(f"Work Orders Path : {wo_path}")
            print(f"Total Work Orders : {len(wo_registry.work_orders)}")
            print(f"Validation        : {'PASSED' if is_wo_valid else 'FAILED'}")
            print(f"Stable Hash       : {wo_res['stable_hash']}")
            print("-" * 70)
            if not is_wo_valid:
                print(f"ERRORS ({len(wo_errors)}):")
                for err in wo_errors:
                    print(f"  [X] {err}")
        return 0 if is_wo_valid else 1

    res = run_validation(reg_path, max_freshness_days=args.max_freshness_days)
    is_valid = res["valid"]

    default_wo = Path("data/source_adaptation_work_orders.json")
    if not args.hash and default_wo.exists() and registry is not None:
        try:
            wo_registry = WorkOrderRegistry.load_from_file(default_wo.resolve())
            corr = validate_source_work_order_correspondence(
                registry, list(wo_registry.work_orders.values())
            )
            if corr:
                res.setdefault("errors", []).extend(corr)
                res["valid"] = False
                is_valid = False
        except Exception as e:
            res.setdefault("errors", []).append(f"Failed to load work orders for correspondence: {e}")
            res["valid"] = False
            is_valid = False

    # Always redact secret-shaped tokens in outputs
    sanitized_res = redact_secrets(res)

    if args.hash:
        print(sanitized_res.get("stable_hash", ""))
        return 0 if is_valid else 1

    if args.json:
        print(json.dumps(sanitized_res, indent=2))
        return 0 if is_valid else 1

    if not args.quiet:
        print("=" * 70)
        print("MarketOS Source Adaptation Governance Validation")
        print("=" * 70)
        print(f"Registry Path : {reg_path}")
        print(f"Total Sources : {res['total_sources']}")
        print(f"Validation    : {'PASSED' if is_valid else 'FAILED'}")
        print(f"Stable Hash   : {res['stable_hash']}")
        print("-" * 70)

        if args.summary or not is_valid:
            summary = res.get("summary", {})
            print("Modes Breakdown:")
            for mode, count in summary.get("modes", {}).items():
                print(f"  - {mode:<18}: {count}")

            print("\nStatuses Breakdown:")
            for status, count in summary.get("statuses", {}).items():
                print(f"  - {status:<18}: {count}")

            print("\nTarget Authorities Breakdown:")
            for auth, count in summary.get("target_authorities", {}).items():
                print(f"  - {auth:<40}: {count}")

            print("-" * 70)

        if not is_valid:
            print(f"ERRORS ENCOUNTERED ({len(res['errors'])}):")
            for err in res["errors"]:
                print(f"  [X] {err}")
            print("-" * 70)

    return 0 if is_valid else 1



if __name__ == "__main__":
    sys.exit(main())
