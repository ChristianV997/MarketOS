"""Validate the internal-only n8n Compose overlay without Docker."""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
OVERLAY = ROOT / "docker-compose.n8n.internal.example.yml"


def validate_overlay(path: Path = OVERLAY) -> list[str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    services = data.get("services", {})
    n8n = services.get("n8n", {})
    api = services.get("api", {})
    errors: list[str] = []
    if not n8n or not api:
        return ["internal n8n overlay must define n8n and api services"]
    image = str(n8n.get("image", ""))
    if not image or ":latest" in image or "@sha256:" not in image and ":" not in image:
        errors.append("n8n image must be explicitly pinned")
    if n8n.get("ports"):
        errors.append("n8n internal overlay must not publish a host port")
    if "healthcheck" not in n8n:
        errors.append("n8n internal overlay must define a healthcheck")
    environment = n8n.get("environment", {})
    for key in ("N8N_ENCRYPTION_KEY", "N8N_USER_MANAGEMENT_JWT_SECRET"):
        if not environment.get(key):
            errors.append(f"n8n must require {key}")
    api_env = api.get("environment", {})
    if api_env.get("N8N_BASE_URL") != "http://n8n:5678":
        errors.append("api must target the internal n8n service")
    if api_env.get("N8N_ALLOWED_HOSTS") != "n8n":
        errors.append("api must allowlist only the internal n8n host")
    if not api_env.get("N8N_WEBHOOK_TOKEN"):
        errors.append("api must require the n8n webhook token")
    if api.get("depends_on", {}).get("n8n", {}).get("condition") != "service_healthy":
        errors.append("api must depend on n8n service_healthy")
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
    print(f"Internal n8n Compose overlay valid: {args.overlay}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
