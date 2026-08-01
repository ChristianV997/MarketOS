"""Verify MarketOS's local Ollama and Obsidian development integrations."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx


def find_vault() -> Path | None:
    appdata = os.environ.get("APPDATA")
    config = Path(appdata or "") / "obsidian" / "obsidian.json"
    if not config.exists():
        return None
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
        for value in data.get("vaults", {}).values():
            if value.get("path"):
                path = Path(value["path"])
                if path.is_dir():
                    return path
    except (OSError, json.JSONDecodeError, TypeError, AttributeError):
        return None
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, help="also capture this Markdown handoff into Obsidian")
    args = parser.parse_args()

    model = os.environ.setdefault("OLLAMA_MODEL", "qwen2.5:0.5b")
    base = os.environ.setdefault("OLLAMA_URL", "http://localhost:11434")
    checks: dict[str, object] = {"ollama_url": base, "ollama_model": model}
    try:
        tags = httpx.get(f"{base}/api/tags", timeout=5).json()
        names = {item.get("name") for item in tags.get("models", [])}
        checks["ollama_api"] = True
        checks["ollama_model_present"] = model in names
    except (httpx.HTTPError, ValueError, KeyError):
        checks["ollama_api"] = False
        checks["ollama_model_present"] = False

    vault = find_vault()
    checks["obsidian_vault"] = str(vault) if vault else None
    checks["obsidian_handoff_dir"] = str(vault / "AI Engineering" / "Session Handoffs") if vault else None

    if args.capture:
        if not vault:
            parser.error("cannot capture: no configured Obsidian vault found")
        destination = vault / "AI Engineering" / "Session Handoffs" / args.capture.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(args.capture.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        checks["captured_handoff"] = str(destination)

    print(json.dumps(checks, indent=2))
    return 0 if checks["ollama_api"] and checks["ollama_model_present"] and vault else 1


if __name__ == "__main__":
    raise SystemExit(main())
