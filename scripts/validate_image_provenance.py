"""Check that MarketOS images carry minimum OCI provenance labels."""
from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).parents[1]
DOCKERFILE = ROOT / "Dockerfile"
REQUIRED = {
    'org.opencontainers.image.source="https://github.com/ChristianV997/MarketOS"',
    'org.opencontainers.image.revision="${VCS_REF}"',
}


def validate_dockerfile(path: Path = DOCKERFILE) -> list[str]:
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    if "ARG VCS_REF=" not in text:
        errors.append("Dockerfile must declare VCS_REF build argument")
    for marker in REQUIRED:
        if marker not in text:
            errors.append(f"Dockerfile is missing OCI provenance label: {marker}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dockerfile", type=Path, default=DOCKERFILE)
    args = parser.parse_args()
    errors = validate_dockerfile(args.dockerfile)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"Image provenance labels valid: {args.dockerfile}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
