"""Report evidence for the MarketOS OSS integration acceptance criteria.

The report never enables sidecars or performs mutations. It distinguishes
static/dry-run proof from live validation that necessarily requires reviewed
external credentials, a Docker runtime, and (for Postiz) legal approval.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_oss_policy import check_policy
from scripts.validate_container_pins import validate_manifests
from scripts.validate_image_provenance import validate_dockerfile
from scripts.validate_license_manifest import validate_manifest
from scripts.validate_n8n_internal_compose import validate_overlay as validate_n8n
from scripts.validate_oss_compose import validate_overlay as validate_oss
from scripts.validate_oss_runtime import build_report
from scripts.validate_postiz_compose import validate_overlay as validate_postiz


def build_readiness_report() -> dict[str, Any]:
    static_checks = {
        "oss_policy": check_policy(),
        "license_manifest": validate_manifest(),
        "container_pins": validate_manifests(),
        "image_provenance": validate_dockerfile(),
        "commerce_and_browser_overlay": validate_oss(),
        "internal_n8n_overlay": validate_n8n(),
        "approval_gated_postiz_overlay": validate_postiz(),
    }
    runtime = build_report()
    external = {
        "docker_available": shutil.which("docker") is not None,
        "medusa_live_smoke": "requires a reviewed MEDUSA_IMAGE, database, Docker, and explicit --execute --teardown",
        "crawl4ai_live_smoke": "requires an installed worker profile and approved source domains",
        "browser_use_live_smoke": "requires the isolated worker image, private token, approved domains, and a human-approved workflow",
        "pydantic_ai_live_smoke": "requires the optional profile and a configured model provider",
        "postiz_live_smoke": "requires a configured service and explicit AGPL commercial approval",
        "n8n_live_smoke": "requires the internal-only overlay and workflow Header Auth configuration",
    }
    return {
        "format": "marketos-oss-readiness-v1",
        "read_only": True,
        "static_checks": static_checks,
        "static_ready": all(not errors for errors in static_checks.values()) and not runtime["inventory_errors"],
        "runtime_dry_run": runtime,
        "external_validation": external,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    report = build_readiness_report()
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        status = "PASS" if report["static_ready"] else "FAIL"
        print(f"OSS static readiness: {status}")
        for name, errors in report["static_checks"].items():
            print(f"- {name}: {'PASS' if not errors else 'FAIL'}")
        print(f"- docker_available: {report['external_validation']['docker_available']}")
    return 0 if report["static_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
