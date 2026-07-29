#!/usr/bin/env bash
# Installs MarketOS's orchestrator as a persistent background service on
# this machine: systemd on Linux, launchd on macOS. Not run automatically —
# read it, then execute it yourself:
#
#   ./scripts/install_daemon.sh
#
# What it does:
#   1. Creates ~/marketos-data/ (DuckDB state, JSONL logs, Obsidian vault).
#   2. Pulls the recommended Ollama model (mistral:7b) if Ollama is running.
#   3. Renders the systemd unit / launchd plist template with real paths
#      and installs + starts it.
#
# Safe to re-run: re-installing just restarts the service with the current
# repo checkout.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${MARKETOS_DATA_DIR:-$HOME/marketos-data}"
PYTHON_BIN="$(command -v python3 || command -v python)"
CURRENT_USER="$(id -un)"

echo "MarketOS orchestrator daemon installer"
echo "  repo:   $REPO_DIR"
echo "  data:   $DATA_DIR"
echo "  python: $PYTHON_BIN"
echo

mkdir -p "$DATA_DIR/state" "$DATA_DIR/obsidian-vault" "$DATA_DIR/logs"

if [ ! -f "$REPO_DIR/.env" ]; then
    echo "No .env found at $REPO_DIR/.env — copying .env.example."
    echo "Edit it before the service starts handling real credentials."
    cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
fi

# ── Ollama model pull (best-effort; orchestrator also self-heals this) ───────
if command -v ollama >/dev/null 2>&1; then
    if curl -fsS --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
        echo "Ollama daemon is running — pulling mistral:7b (needs ~2GB RAM/VRAM free)..."
        ollama pull mistral:7b || echo "  warning: model pull failed, orchestrator will retry at runtime"
    else
        echo "Ollama daemon not running yet — the service (OLLAMA_AUTO_START=true) will try to start it."
    fi
else
    echo "warning: 'ollama' not found on PATH. Install it from https://ollama.com before starting the service,"
    echo "         or unset OLLAMA_AUTO_START / remove ollama from INFERENCE_PROVIDERS to run cloud-only."
fi
echo

OS_NAME="$(uname -s)"

case "$OS_NAME" in
    Linux)
        UNIT_SRC="$REPO_DIR/contrib/systemd/marketos-orchestrator.service"
        UNIT_DST="$HOME/.config/systemd/user/marketos-orchestrator.service"
        mkdir -p "$(dirname "$UNIT_DST")"

        sed \
            -e "s#__MARKETOS_REPO_DIR__#$REPO_DIR#g" \
            -e "s#__MARKETOS_DATA_DIR__#$DATA_DIR#g" \
            -e "s#__MARKETOS_PYTHON_BIN__#$PYTHON_BIN#g" \
            "$UNIT_SRC" > "$UNIT_DST"

        systemctl --user daemon-reload
        systemctl --user enable --now marketos-orchestrator.service
        echo "Installed. Check status with:"
        echo "  systemctl --user status marketos-orchestrator"
        echo "  journalctl --user -u marketos-orchestrator -f"
        echo
        echo "For it to survive logout, enable lingering once (needs sudo):"
        echo "  sudo loginctl enable-linger $CURRENT_USER"
        ;;

    Darwin)
        PLIST_SRC="$REPO_DIR/contrib/launchd/com.marketos.orchestrator.plist"
        PLIST_DST="$HOME/Library/LaunchAgents/com.marketos.orchestrator.plist"
        mkdir -p "$(dirname "$PLIST_DST")"

        sed \
            -e "s#__MARKETOS_REPO_DIR__#$REPO_DIR#g" \
            -e "s#__MARKETOS_DATA_DIR__#$DATA_DIR#g" \
            -e "s#__MARKETOS_PYTHON_BIN__#$PYTHON_BIN#g" \
            "$PLIST_SRC" > "$PLIST_DST"

        launchctl unload "$PLIST_DST" >/dev/null 2>&1 || true
        launchctl load -w "$PLIST_DST"
        echo "Installed. Check status with:"
        echo "  launchctl list | grep com.marketos.orchestrator"
        echo "  tail -f $DATA_DIR/logs/orchestrator.out.log"
        ;;

    *)
        echo "Unsupported OS: $OS_NAME. Run the orchestrator directly instead:"
        echo "  cd $REPO_DIR && STATE_PATH=$DATA_DIR/state.db MARKETOS_STATE_DIR=$DATA_DIR/state python -m orchestrator.main"
        exit 1
        ;;
esac
