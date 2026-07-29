"""Static validation for the opt-in OSS Compose overlay when Docker is absent."""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
OVERLAY = ROOT / "docker-compose.oss.example.yml"


def validate_overlay(path: Path = OVERLAY) -> list[str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    errors: list[str] = []
    services = data.get("services", {})
    medusa = services.get("medusa", {})
    api = services.get("api", {})
    browser_worker = services.get("browser-use-worker", {})
    if "medusa" not in services or "api" not in services:
        errors.append("overlay must define medusa and api services")
    if ":latest" in str(medusa.get("image", "")) or medusa.get("image") is None:
        errors.append("medusa image must be an explicitly pinned variable")
    if "healthcheck" not in medusa:
        errors.append("medusa must define a healthcheck")
    if api.get("environment", {}).get("MEDUSA_BASE_URL") != "http://medusa:9000":
        errors.append("api must target the internal medusa service")
    condition = api.get("depends_on", {}).get("medusa", {}).get("condition")
    if condition != "service_healthy":
        errors.append("api must depend on medusa service_healthy")
    if "browser-use-worker" not in services:
        errors.append("overlay must define the browser-use worker service")
    if "healthcheck" not in browser_worker:
        errors.append("browser-use worker must define a healthcheck")
    build = browser_worker.get("build", {})
    if not isinstance(build, dict) or build.get("dockerfile") != "Dockerfile.browser-use-worker":
        errors.append("browser-use worker must use the reviewed worker Dockerfile")
    version = build.get("args", {}).get("BROWSER_USE_VERSION", "") if isinstance(build, dict) else ""
    if not version or "latest" in str(version):
        errors.append("browser-use worker version must be explicitly pinned")
    if browser_worker.get("ports"):
        errors.append("browser-use worker must not publish a host port")
    if api.get("environment", {}).get("BROWSER_USE_WORKER_URL") != "http://browser-use-worker:8001":
        errors.append("api must target the internal browser-use worker")
    browser_condition = api.get("depends_on", {}).get("browser-use-worker", {}).get("condition")
    if browser_condition != "service_healthy":
        errors.append("api must depend on browser-use worker service_healthy")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overlay", type=Path, default=OVERLAY)
    args = parser.parse_args()
    errors = validate_overlay(args.overlay)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"OSS Compose overlay valid: {args.overlay}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
