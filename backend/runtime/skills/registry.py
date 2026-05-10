from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.events.schemas import SKILL_EXECUTED, SKILL_FAILED, TASK_INVENTORY


def _serialize(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        try:
            return value.to_dict()
        except Exception:
            pass
    if hasattr(value, "__dataclass_fields__"):
        try:
            from dataclasses import asdict

            return asdict(value)
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


@dataclass
class SkillRecord:
    name: str
    description: str
    category: str
    related_tasks: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "related_tasks": list(self.related_tasks),
            "params": dict(self.params),
        }


class SkillRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._skills: dict[str, tuple[SkillRecord, Callable[[dict[str, Any]], Any]]] = {}
        self._traces: deque[dict[str, Any]] = deque(maxlen=100)
        self._register_builtin_skills()

    def register(
        self,
        record: SkillRecord,
        handler: Callable[[dict[str, Any]], Any],
    ) -> None:
        with self._lock:
            self._skills[record.name] = (record, handler)

    def list_skills(self) -> list[dict[str, Any]]:
        with self._lock:
            skills = [record.to_dict() for record, _ in self._skills.values()]
        return sorted(skills, key=lambda skill: skill["name"])

    def traces(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._traces)

    def execute(self, name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = payload or {}
        with self._lock:
            entry = self._skills.get(name)
        if entry is None:
            raise KeyError(name)

        record, handler = entry
        trace = {
            "trace_id": uuid.uuid4().hex[:12],
            "skill": name,
            "started_at": time.time(),
            "input": _serialize(data),
        }

        try:
            result = handler(data)
            trace["status"] = "ok"
            trace["result"] = _serialize(result)
            return {
                "skill": record.to_dict(),
                "trace": trace,
                "result": trace["result"],
            }
        except Exception as exc:
            trace["status"] = "error"
            trace["error"] = str(exc)
            raise
        finally:
            trace["finished_at"] = time.time()
            trace["duration_ms"] = round((trace["finished_at"] - trace["started_at"]) * 1000, 3)
            self._record_trace(trace)
            self._emit_trace(trace)

    def _record_trace(self, trace: dict[str, Any]) -> None:
        with self._lock:
            self._traces.appendleft(dict(trace))

    def _emit_trace(self, trace: dict[str, Any]) -> None:
        try:
            from backend.pubsub.broker import get_broker

            event_type = SKILL_EXECUTED if trace.get("status") == "ok" else SKILL_FAILED
            payload = {
                "type": event_type,
                "skill": trace.get("skill", ""),
                "trace_id": trace.get("trace_id", ""),
                "status": trace.get("status", "unknown"),
                "duration_ms": trace.get("duration_ms", 0.0),
                "ts": trace.get("finished_at", time.time()),
            }
            if "error" in trace:
                payload["error"] = trace["error"]
            get_broker().publish(event_type, payload, source="skills")
        except Exception:
            pass

    def _register_builtin_skills(self) -> None:
        self.register(
            SkillRecord(
                name="signal_ingestion",
                description="Run the existing signal ingestion worker once.",
                category="runtime",
                related_tasks=["signal_ingestion_worker"],
            ),
            self._run_signal_ingestion,
        )
        self.register(
            SkillRecord(
                name="playbook_generation",
                description="Run the existing creative/playbook generation worker once.",
                category="runtime",
                related_tasks=["content_generation_worker"],
            ),
            self._run_playbook_generation,
        )
        self.register(
            SkillRecord(
                name="semantic_search",
                description="Run semantic search across the vector collections.",
                category="memory",
                related_tasks=["sw_creative_memory", "sw_pattern_store"],
                params={"query": "str", "top_k": "int?", "threshold": "float?"},
            ),
            self._run_semantic_search,
        )
        self.register(
            SkillRecord(
                name="runtime_inspection",
                description="Inspect the runtime task inventory and cognition summary.",
                category="observability",
                related_tasks=[TASK_INVENTORY],
            ),
            self._run_runtime_inspection,
        )
        self.register(
            SkillRecord(
                name="safe_command",
                description="Execute an allowlisted command in the command sandbox.",
                category="tooling",
                params={"command": "str"},
            ),
            self._run_safe_command,
        )

    @staticmethod
    def _run_signal_ingestion(_: dict[str, Any]) -> Any:
        from orchestrator.main import _run_signal_ingestion

        return _run_signal_ingestion()

    @staticmethod
    def _run_playbook_generation(_: dict[str, Any]) -> Any:
        from orchestrator.main import _run_content_generation

        return _run_content_generation()

    @staticmethod
    def _run_semantic_search(payload: dict[str, Any]) -> dict[str, Any]:
        from backend.vector.semantic_search import search_all

        query = str(payload.get("query", "")).strip()
        if not query:
            raise ValueError("query is required")
        top_k = int(payload.get("top_k", 5))
        threshold = float(payload.get("threshold", 0.0))
        results = search_all(query, top_k=top_k, threshold=threshold)
        return {
            collection: [
                {
                    "record_id": hit.record_id,
                    "score": hit.score,
                    "payload": hit.payload,
                    "collection": hit.collection,
                }
                for hit in hits
            ]
            for collection, hits in results.items()
        }

    @staticmethod
    def _run_runtime_inspection(_: dict[str, Any]) -> dict[str, Any]:
        from backend.runtime.task_inventory import task_registry
        from backend.runtime.topology.cognition_map import cognition_map

        return {
            "summary": task_registry.summary(),
            "live_threads": task_registry.live_threads(),
            "cognition": cognition_map(),
        }

    @staticmethod
    def _run_safe_command(payload: dict[str, Any]) -> dict[str, Any]:
        from backend.runtime.security.command_sandbox import CommandSandbox

        command = str(payload.get("command", "")).strip()
        return CommandSandbox().execute(command)


_registry: SkillRegistry | None = None
_registry_lock = threading.Lock()


def get_skill_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = SkillRegistry()
    return _registry
