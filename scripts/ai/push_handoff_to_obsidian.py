"""Safely copy a generated session handoff into the configured Obsidian vault."""
from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path


def configured_vault() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    config = Path(appdata) / "obsidian" / "obsidian.json"
    if not config.exists():
        return None
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
        vaults = data.get("vaults", {})
        paths = [Path(item["path"]) for item in vaults.values() if item.get("path")]
        return paths[0] if paths else None
    except (OSError, json.JSONDecodeError, TypeError, KeyError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Markdown handoff to capture")
    parser.add_argument("--vault", type=Path, help="explicit vault path; otherwise use Obsidian config")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source = args.input.resolve()
    vault = (args.vault or configured_vault())
    if not source.is_file():
        parser.error(f"handoff does not exist: {source}")
    if not vault:
        parser.error("no Obsidian vault was found; pass --vault explicitly")
    vault = vault.resolve()
    if not vault.is_dir():
        parser.error(f"vault is not a directory: {vault}")

    destination_dir = vault / "AI Engineering" / "Session Handoffs"
    destination = destination_dir / f"{date.today().isoformat()}-{source.stem}.md"
    if args.dry_run:
        print(destination)
        return 0
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination.write_text(source.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
