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
from typing import Any, Dict

# Ensure repo root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evaluation.source_governance.registry import SourceAdaptationRegistry, redact_secrets
from evaluation.source_governance.validator import validate_registry


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

    res = run_validation(reg_path, max_freshness_days=args.max_freshness_days)
    is_valid = res["valid"]

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
