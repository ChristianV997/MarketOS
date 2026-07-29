"""Small, cross-platform runtime inspection command sandbox."""
from __future__ import annotations

import os
import shlex
from pathlib import Path


class CommandSandbox:
    """Implement a tiny allowlist without invoking a platform shell."""

    SAFE_COMMANDS = ("echo", "ls", "pwd")

    @staticmethod
    def _success(stdout: str) -> dict:
        return {
            "success": True,
            "exit_ok": True,
            "stdout": stdout,
            "stderr": "",
            "returncode": 0,
        }

    def execute(self, command: str) -> dict:
        try:
            parts = shlex.split(command)
        except ValueError as exc:
            return {"success": False, "error": f"invalid command: {exc}"}
        if not parts:
            return {"success": False, "error": "empty command"}
        if parts[0] not in self.SAFE_COMMANDS:
            return {"success": False, "error": "command blocked"}

        name, args = parts[0], parts[1:]
        if name == "pwd":
            if args:
                return {"success": False, "error": "pwd does not accept arguments"}
            return self._success(f"{os.getcwd()}\n")
        if name == "echo":
            return self._success(" ".join(args) + "\n")

        # ``ls`` is intentionally limited to the current workspace. This
        # permits inspection while preventing the runtime endpoint from being
        # used to enumerate arbitrary host directories.
        if len(args) > 1:
            return {"success": False, "error": "ls accepts at most one path"}
        root = Path.cwd().resolve()
        target = (root / (args[0] if args else ".")).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return {"success": False, "error": "path outside workspace blocked"}
        if not target.exists():
            return {"success": False, "error": "path not found"}
        if target.is_file():
            return self._success(f"{target.name}\n")
        return self._success("\n".join(sorted(item.name for item in target.iterdir())) + "\n")
