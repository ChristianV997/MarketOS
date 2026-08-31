#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for MarketOS.
# System toolchains (Python 3.12, Node 22) come from the base image; this
# script only refreshes repository-scoped dependencies against the checkout.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if ! python3 -c "import ensurepip" >/dev/null 2>&1; then
  echo "ensurepip is unavailable; rebuild the Cloud Agent image with python3-venv enabled" >&2
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

lockfile="$repo_root/frontend/package-lock.json"
if [ ! -f "$lockfile" ]; then
  echo "frontend/package-lock.json is required for reproducible Cloud Agent setup" >&2
  exit 1
fi

npm --prefix frontend ci --ignore-scripts --no-audit --no-fund

bash "$repo_root/.cursor/validate.sh"

echo "MarketOS environment ready."
