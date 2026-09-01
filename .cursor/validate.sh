#!/usr/bin/env bash
# Offline contract validation for the Cursor Cloud Agent environment.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [ ! -f frontend/package-lock.json ]; then
  echo "frontend/package-lock.json is required for reproducible setup" >&2
  exit 1
fi

node --test .cursor/environment.contract.test.mjs

echo "cursor environment contract ok"
