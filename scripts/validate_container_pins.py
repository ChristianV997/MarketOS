"""Reject mutable container image tags in MarketOS Compose manifests."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
DEFAULT_MANIFESTS = (
    ROOT / "docker-compose.yml",
    ROOT / "docker-compose.prod.yml",
    ROOT / "docker-compose.oss.example.yml",
    ROOT / "docker-compose.n8n.internal.example.yml",
    ROOT / "docker-compose.postiz.example.yml",
)
_VERSION_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_manifests(paths: tuple[Path, ...] = DEFAULT_MANIFESTS) -> list[str]:
    """Return deterministic policy errors without contacting a registry."""
    errors: list[str] = []
    for path in paths:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        services = data.get("services", {})
        if not isinstance(services, dict):
            errors.append(f"{path.name}: services must be a mapping")
            continue
        for service, config in services.items():
            if not isinstance(config, dict) or "image" not in config:
                continue
            image = str(config["image"] or "").strip()
            if not image:
                errors.append(f"{path.name}:{service}: image must not be empty")
                continue
            # The opt-in Medusa overlay intentionally receives its reviewed
            # pinned image through CI/deployment configuration.
            if "${" in image or "@sha256:" in image:
                continue
            if ":" not in image.rsplit("/", 1)[-1]:
                errors.append(f"{path.name}:{service}: image must use an immutable version tag or digest")
                continue
            tag = image.rsplit(":", 1)[1]
            if tag.lower() == "latest" or not _VERSION_TAG.fullmatch(tag):
                errors.append(f"{path.name}:{service}: mutable or invalid image tag: {image}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", action="append", type=Path, dest="manifests")
    args = parser.parse_args()
    manifests = tuple(args.manifests) if args.manifests else DEFAULT_MANIFESTS
    errors = validate_manifests(manifests)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Container image pin policy valid:", ", ".join(path.name for path in manifests))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
