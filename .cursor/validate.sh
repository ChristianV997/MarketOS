#!/usr/bin/env bash
# Offline contract validation for the Cursor Cloud Agent environment.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

python3 - <<'PY'
import json
from pathlib import Path

root = Path(".")
env_path = root / ".cursor" / "environment.json"
install_path = root / ".cursor" / "install.sh"
lockfile = root / "frontend" / "package-lock.json"

env = json.loads(env_path.read_text(encoding="utf-8"))
assert env.get("install") == "bash .cursor/install.sh"
assert isinstance(env.get("terminals"), list) and len(env["terminals"]) == 2
assert isinstance(env.get("ports"), list) and len(env["ports"]) == 2
for terminal in env["terminals"]:
    command = terminal.get("command", "")
    assert "127.0.0.1" in command
    assert "0.0.0.0" not in command

install = install_path.read_text(encoding="utf-8")
for forbidden in ("sudo ", "npm install", "apt-get install"):
    assert forbidden not in install, f"forbidden bootstrap marker: {forbidden}"
assert "npm --prefix frontend ci --ignore-scripts --no-audit --no-fund" in install

if not lockfile.is_file():
    raise SystemExit("frontend/package-lock.json is required for reproducible setup")

print("cursor environment contract ok")
PY
