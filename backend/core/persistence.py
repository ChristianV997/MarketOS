"""backend.core.persistence — shared JSON snapshot helpers.

One atomic, fail-silent JSON persistence idiom used by every in-process store
that needs to survive a restart (PatternStore, PlaybookMemory, CalibrationStore,
LineageTracker, EpisodicStore).  stdlib only — no new dependencies.

Design:
  * Writes go through a temp file + ``os.replace`` so a crash mid-write never
    corrupts the existing snapshot (atomic on POSIX).
  * All failures are swallowed and logged at debug level — persistence is
    best-effort and must never disturb the caller.
  * Paths default under ``state/`` (git-ignored); the directory is created on
    demand.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

_log = logging.getLogger(__name__)

# Base directory for all snapshots (overridable for tests / deployment).
STATE_DIR = os.getenv("MARKETOS_STATE_DIR", "state")


def state_path(name: str) -> str:
    """Return the full path for a snapshot file *name* under STATE_DIR."""
    return os.path.join(STATE_DIR, name)


def save_json_atomic(path: str, data: Any) -> bool:
    """Atomically write *data* as JSON to *path*.  Returns True on success.

    Never raises — a failed persist logs at debug level and returns False.
    """
    if not path:
        return False
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except Exception as exc:  # noqa: BLE001 — best-effort persistence
        _log.debug("persist_failed path=%s error=%s", path, exc)
        return False


def save_text_atomic(path: str, text: str) -> bool:
    """Atomically write UTF-8 text using the shared persistence convention."""
    if not path:
        return False
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, path)
        return True
    except Exception as exc:  # noqa: BLE001
        _log.debug("persist_text_failed path=%s error=%s", path, exc)
        return False


def load_json(path: str, default: Any = None) -> Any:
    """Load JSON from *path*, returning *default* if missing or unreadable.

    Never raises.
    """
    if not path or not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:  # noqa: BLE001 — best-effort recovery
        _log.debug("load_failed path=%s error=%s", path, exc)
        return default
