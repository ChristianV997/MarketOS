"""Validate the explicit-approval Postiz sidecar overlay without Docker."""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
OVERLAY = ROOT / "docker-compose.postiz.example.yml"


def validate_overlay(path: Path = OVERLAY) -> list[str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    services = data.get("services", {})
    postiz = services.get("postiz", {})
    api = services.get("api", {})
    errors: list[str] = []
    if not postiz or not api:
        return ["Postiz overlay must define postiz and api services"]
    image = str(postiz.get("image", ""))
    if "@sha256:" not in image or ":latest" in image:
        errors.append("Postiz image must use a reviewed immutable digest")
    if postiz.get("ports"):
        errors.append("Postiz sidecar must not publish a host port directly")
    if "healthcheck" not in postiz:
        errors.append("Postiz sidecar must define a healthcheck")
    environment = postiz.get("environment", {})
    for key in ("MAIN_URL", "FRONTEND_URL", "NEXT_PUBLIC_BACKEND_URL", "JWT_SECRET", "DISABLE_REGISTRATION"):
        if not environment.get(key):
            errors.append(f"Postiz sidecar must configure {key}")
    api_env = api.get("environment", {})
    if api_env.get("POSTIZ_BASE_URL") != "http://postiz:5000/public/v1":
        errors.append("api must target the internal Postiz public API")
    if api_env.get("POSTIZ_ALLOWED_HOSTS") != "postiz":
        errors.append("api must allowlist only the internal Postiz host")
    if not api_env.get("POSTIZ_COMMERCIAL_APPROVED"):
        errors.append("Postiz overlay must require explicit commercial approval")
    if api.get("depends_on", {}).get("postiz", {}).get("condition") != "service_healthy":
        errors.append("api must depend on Postiz service_healthy")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overlay", type=Path, default=OVERLAY)
    args = parser.parse_args()
    errors = validate_overlay(args.overlay)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"Postiz Compose overlay valid: {args.overlay}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
