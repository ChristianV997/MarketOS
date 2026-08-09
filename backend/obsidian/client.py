from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class ObsidianClient:
    """Small local-vault bridge; deliberately no REST/MCP or network behavior."""
    def __init__(self, vault_path: str | os.PathLike[str] | None = None) -> None:
        self.vault_path = Path(vault_path or os.getenv("OBSIDIAN_VAULT_PATH", "")).expanduser() if (vault_path or os.getenv("OBSIDIAN_VAULT_PATH")) else None
    def configured(self) -> bool: return self.vault_path is not None
    def _safe(self, relative_path: str) -> Path | None:
        if not self.vault_path or not relative_path or Path(relative_path).is_absolute(): return None
        root = self.vault_path.resolve(); candidate = (root / relative_path).resolve()
        try: candidate.relative_to(root)
        except ValueError: return None
        return candidate
    def write_note(self, relative_path: str, content: str) -> dict[str, Any]:
        path = self._safe(relative_path)
        if not self.configured(): return {"status": "skipped", "reason": "not_configured"}
        if path is None: return {"status": "blocked", "reason": "unsafe_path"}
        try: path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content, encoding="utf-8"); return {"status": "written", "path": str(path)}
        except Exception as exc: return {"status": "error", "reason": type(exc).__name__}
    def read_note(self, relative_path: str) -> dict[str, Any]:
        path = self._safe(relative_path)
        if not self.configured(): return {"status": "skipped", "reason": "not_configured"}
        if path is None: return {"status": "blocked", "reason": "unsafe_path"}
        try: return {"status": "read", "path": str(path), "content": path.read_text(encoding="utf-8")}
        except FileNotFoundError: return {"status": "not_found", "path": str(path)}
        except Exception as exc: return {"status": "error", "reason": type(exc).__name__}
    def append_note(self, relative_path: str, content: str) -> dict[str, Any]:
        path = self._safe(relative_path)
        if not self.configured(): return {"status": "skipped", "reason": "not_configured"}
        if path is None: return {"status": "blocked", "reason": "unsafe_path"}
        try:
            path.parent.mkdir(parents=True, exist_ok=True); with_open = path.open("a", encoding="utf-8"); with_open.write(content); with_open.close(); return {"status": "written", "path": str(path)}
        except Exception as exc: return {"status": "error", "reason": type(exc).__name__}
