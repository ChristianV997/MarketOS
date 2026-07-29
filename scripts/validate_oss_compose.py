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
