#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for MarketOS.
# System toolchains (Python 3.12, Node 22) come from the base image; this
# script only refreshes repository-scoped dependencies against the checkout.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

# The base image ships python3.12 but not the stdlib venv/ensurepip module.
if ! python3 -m venv --help >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3-venv
fi

# Python backend: isolated virtualenv at the repo root.
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install --upgrade pip wheel setuptools
pip install -r requirements.txt -r requirements-dev.txt

# Frontend dashboard dependencies (lockfile-pinned).
npm --prefix frontend ci

echo "MarketOS environment ready."
