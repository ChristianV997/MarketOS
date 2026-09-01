#!/usr/bin/env bash
# Offline contract validation for the Cursor Cloud Agent environment.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [ ! -f frontend/package-lock.json ]; then
  echo "frontend/package-lock.json is required for reproducible setup" >&2
  exit 1
fi

for script in .cursor/install.sh .cursor/validate.sh; do
  if grep -q $'\r' "$repo_root/$script" 2>/dev/null; then
    echo "${script} contains CRLF line endings; run 'git add --renormalize .cursor' or use LF checkout policy" >&2
    exit 1
  fi
done

if ! command -v node >/dev/null 2>&1; then
  echo "node is unavailable in this environment; install Node.js to run environment contract tests" >&2
  exit 127
fi

node --test .cursor/environment.contract.test.mjs

echo "cursor environment contract ok"
