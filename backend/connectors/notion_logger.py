"""notion_logger — best-effort Notion logging connector.

Environment variables:
    NOTION_TOKEN          Bearer token for Notion integration
    NOTION_PATCH_DB_ID    Database id for patch log entries
    NOTION_REPLAY_DB_ID   Database id for replay log entries
    NOTION_RUNS_DB_ID     Database id for pipeline run entries (optional)

All methods are best-effort: they never raise; pipeline continues on any failure.
stdout fallback is always printed regardless of Notion availability.
"""
from __future__ import annotations
import json
import os

_TOKEN = os.getenv("NOTION_TOKEN", "")
_PATCH_DB = os.getenv("NOTION_PATCH_DB_ID", "")
_REPLAY_DB = os.getenv("NOTION_REPLAY_DB_ID", "")
_RUNS_DB = os.getenv("NOTION_RUNS_DB_ID", "")


def _stable_json(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


class NotionLogger:
    def log_patch(self, patch: dict) -> str | None:
        """Log a patch record. Not invoked in this patch — implemented for future use."""
        return self._log("patch", _PATCH_DB, patch.get("name", "patch"), patch)

    def log_replay(self, replay: dict) -> str | None:
        """Log a replay record. Not invoked in this patch — implemented for future use."""
        return self._log("replay", _REPLAY_DB, replay.get("task", "replay"), replay)

    def log_run(self, run: dict) -> str | None:
        """Log a pipeline run summary."""
        name = run.get("pipeline_entrypoint", "run")
        return self._log("run", _RUNS_DB, name, run)

    def _log(self, kind: str, db_id: str, name: str, payload: dict) -> str | None:
        serialized = _stable_json(payload)
        print(f"[notion-{kind}] {serialized}")
        if not _TOKEN or not db_id:
            print("[notion] disabled (missing env)")
            return None
        try:
            from backend.connectors.notion_client import create_page
            return create_page(_TOKEN, db_id, name, serialized)
        except Exception as exc:
            print(f"[notion-error] {exc}")
            return None
