"""Isolated Agent-Reach, Hermes, and DeerFlow research adapters.

No dependency on any upstream project is imported here. Agent-Reach is a
capability layer whose concrete readers vary, so MarketOS invokes an explicit
JSON-over-stdin bridge. Hermes and DeerFlow are contacted only through their
documented local HTTP surfaces. Outputs are validated by the governed swarm
contract before persistence.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import time
import uuid
from dataclasses import replace
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.contracts.adapters import AdapterHealth
from backend.research.swarm import EvidenceEnvelope, SwarmJobSpec, canonical_json


class SidecarAdapterError(RuntimeError):
    """Raised when a configured sidecar cannot produce a valid response."""


def _flag(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}


def _timeout(spec: Mapping[str, Any]) -> float:
    try:
        return max(0.001, min(float(spec.get("max_duration_s", 60.0)), 900.0))
    except (TypeError, ValueError):
        return 60.0


def _command_from_env(name: str) -> tuple[str, ...]:
    value = os.getenv(name, "").strip()
    if not value:
        return ()
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list) and all(isinstance(item, str) and item for item in parsed):
            return tuple(parsed)
    except json.JSONDecodeError:
        pass
    return tuple(shlex.split(value, posix=os.name != "nt"))


class AgentReachSensorAdapter:
    """Invoke an operator-supplied Agent-Reach bridge without shell access."""

    name = "agent_reach"

    def __init__(self, *, command: Sequence[str] | None = None, executable: str = "agent-reach", max_output_bytes: int | None = None) -> None:
        self.command = tuple(command or _command_from_env("AGENT_REACH_SENSOR_COMMAND"))
        self.executable = executable
        self.max_output_bytes = max(1_024, int(max_output_bytes or os.getenv("AGENT_REACH_MAX_OUTPUT_BYTES", "512000")))

    def health(self) -> AdapterHealth:
        executable = self.command[0] if self.command else self.executable
        resolved = shutil.which(executable)
        if not self.command:
            return AdapterHealth(self.name, configured=False, reachable=resolved is not None, detail="AGENT_REACH_SENSOR_COMMAND is not configured")
        if resolved is None and not os.path.isabs(executable):
            return AdapterHealth(self.name, configured=True, reachable=False, detail="configured bridge executable is not installed")
        return AdapterHealth(self.name, configured=True, reachable=True, capabilities=("isolated_subprocess", "attributed_evidence"))

    def fetch(self, spec: Mapping[str, Any]) -> Mapping[str, Any]:
        if not _flag("FF_RESEARCH_SENSOR_AGENT_REACH"):
            raise SidecarAdapterError("Agent-Reach sensor flag is disabled")
        if not self.command:
            raise SidecarAdapterError("AGENT_REACH_SENSOR_COMMAND is not configured")
        request = {
            "schema": "MarketOS.AgentReachRequest.v1",
            "request_id": str(uuid.uuid4()),
            "query": str(spec.get("query", "")),
            "objective": str(spec.get("objective", "")),
            "allowed_domains": list(spec.get("allowed_domains") or ()),
            "max_records": int(spec.get("max_records", 50)),
            "dry_run": bool(spec.get("dry_run", True)),
        }
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.startswith(("AGENT_REACH_", "PATH", "HOME", "USERPROFILE", "TEMP", "TMP"))
        }
        try:
            completed = subprocess.run(
                list(self.command), input=canonical_json(request), text=True,
                capture_output=True, timeout=_timeout(spec), check=False, shell=False, env=environment,
            )
        except subprocess.TimeoutExpired as err:
            raise SidecarAdapterError("Agent-Reach bridge timed out") from err
        except OSError as err:
            raise SidecarAdapterError(f"Agent-Reach bridge could not start: {err}") from err
        if completed.returncode != 0:
            raise SidecarAdapterError(f"Agent-Reach bridge exited with code {completed.returncode}")
        output = completed.stdout.encode("utf-8", errors="replace")
        if len(output) > self.max_output_bytes:
            raise SidecarAdapterError("Agent-Reach bridge output exceeded the configured byte limit")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as err:
            raise SidecarAdapterError("Agent-Reach bridge did not return JSON") from err
        if isinstance(payload, list):
            payload = {"records": payload}
        if not isinstance(payload, Mapping):
            raise SidecarAdapterError("Agent-Reach bridge response must be an object or records list")
        return dict(payload)


def _http_json(url: str, payload: Mapping[str, Any], *, headers: Mapping[str, str] | None = None, timeout: float, max_bytes: int = 2_000_000) -> dict[str, Any]:
    request = Request(url, data=canonical_json(payload).encode("utf-8"), headers={"Content-Type": "application/json", **dict(headers or {})}, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(max_bytes + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as err:
        raise SidecarAdapterError(f"sidecar HTTP request failed: {type(err).__name__}") from err
    if len(raw) > max_bytes:
        raise SidecarAdapterError("sidecar response exceeded the configured byte limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise SidecarAdapterError("sidecar response was not JSON") from err
    if not isinstance(payload, dict):
        raise SidecarAdapterError("sidecar response must be a JSON object")
    return payload


def _prompt(spec: Mapping[str, Any], runtime: str) -> str:
    return (
        "Return ONLY a JSON object using schema MarketOS.ResearchEvidence.v1. "
        "Every record must include topic, intent, velocity, competition, "
        "source='agent_reach', freshness_ts, confidence, raw, source_url, "
        "retrieved_at, and provider. Do not invent URLs.\n\n"
        f"job_id: {spec['job_id']}\nquery: {spec['query']}\n"
        f"objective: {spec['objective']}\nruntime: {runtime}\n"
        f"requested sensors: {', '.join(spec.get('sources') or ())}\n"
        f"allowed domains: {', '.join(spec.get('allowed_domains') or ()) or 'none (dry-run only)'}"
    )


def _json_from_text(text: str) -> Mapping[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("\n", 1)[1] if "\n" in candidate else candidate
        candidate = candidate.rsplit("```", 1)[0].strip()
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as err:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            raise SidecarAdapterError("agent runtime did not return a JSON evidence envelope") from err
        try:
            payload = json.loads(candidate[start:end + 1])
        except json.JSONDecodeError as nested:
            raise SidecarAdapterError("agent runtime returned malformed evidence JSON") from nested
    if not isinstance(payload, Mapping):
        raise SidecarAdapterError("agent runtime evidence must be a JSON object")
    return payload


class HermesRuntimeAdapter:
    name = "hermes"

    def __init__(self, *, base_url: str | None = None, token: str | None = None, model: str | None = None, request: Callable[..., Mapping[str, Any]] = _http_json) -> None:
        self.base_url = (base_url or os.getenv("HERMES_URL", "http://127.0.0.1:8642")).rstrip("/")
        self.token = token if token is not None else os.getenv("HERMES_API_TOKEN", "")
        self.model = model or os.getenv("HERMES_MODEL", "hermes-agent")
        self.request = request

    def health(self) -> AdapterHealth:
        configured = bool(os.getenv("HERMES_URL") or os.getenv("HERMES_API_TOKEN"))
        return AdapterHealth(self.name, configured=configured, reachable=False, capabilities=("openai_chat_completions",), detail="reachability is checked on bounded execution")

    def __call__(self, spec: Mapping[str, Any]) -> Mapping[str, Any]:
        if not _flag("FF_RESEARCH_SWARM_HERMES"):
            return {"schema": "MarketOS.ResearchEvidence.v1", "job_id": spec["job_id"], "runtime": self.name, "status": "skipped", "records": []}
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        response = self.request(
            f"{self.base_url}/v1/chat/completions",
            {"model": self.model, "messages": [{"role": "user", "content": _prompt(spec, self.name)}], "stream": False},
            headers=headers, timeout=_timeout(spec),
        )
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as err:
            raise SidecarAdapterError("Hermes response did not contain assistant content") from err
        payload = dict(_json_from_text(str(content)))
        payload.setdefault("schema", "MarketOS.ResearchEvidence.v1")
        payload.setdefault("job_id", spec["job_id"])
        payload.setdefault("runtime", self.name)
        return payload


def _sse_text(raw: bytes) -> str:
    candidates: list[str] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if not line.startswith("data:"):
            continue
        value = line[5:].strip()
        if not value or value == "[DONE]":
            continue
        try:
            event = json.loads(value)
        except json.JSONDecodeError:
            continue
        messages = event.get("messages") if isinstance(event, Mapping) else None
        if isinstance(messages, list):
            for message in reversed(messages):
                if isinstance(message, Mapping) and message.get("content"):
                    candidates.append(str(message["content"]))
        if isinstance(event, Mapping) and event.get("content"):
            candidates.append(str(event["content"]))
    return candidates[-1] if candidates else raw.decode("utf-8", errors="replace")


class DeerFlowRuntimeAdapter:
    name = "deerflow"

    def __init__(self, *, base_url: str | None = None, internal_token: str | None = None, owner_id: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("DEERFLOW_URL", "http://127.0.0.1:2026")).rstrip("/")
        self.internal_token = internal_token if internal_token is not None else os.getenv("DEER_FLOW_INTERNAL_AUTH_TOKEN", "")
        self.owner_id = owner_id or os.getenv("DEER_FLOW_OWNER_USER_ID", "marketos-research")

    def health(self) -> AdapterHealth:
        configured = bool(os.getenv("DEERFLOW_URL") or os.getenv("DEER_FLOW_INTERNAL_AUTH_TOKEN"))
        return AdapterHealth(self.name, configured=configured, reachable=False, capabilities=("langgraph_sse",), detail="reachability is checked on bounded execution")

    def __call__(self, spec: Mapping[str, Any]) -> Mapping[str, Any]:
        if not _flag("FF_RESEARCH_SWARM_DEERFLOW"):
            return {"schema": "MarketOS.ResearchEvidence.v1", "job_id": spec["job_id"], "runtime": self.name, "status": "skipped", "records": []}
        headers = {"Accept": "text/event-stream"}
        if self.internal_token:
            headers.update({"X-DeerFlow-Internal-Token": self.internal_token, "X-DeerFlow-Owner-User-Id": self.owner_id})
        body = {
            "input": {"messages": [{"role": "user", "content": _prompt(spec, self.name)}]},
            "config": {"recursion_limit": int(os.getenv("DEERFLOW_RECURSION_LIMIT", "100")), "configurable": {"model_name": os.getenv("DEERFLOW_MODEL", "")}},
            "stream_mode": ["values", "messages-tuple", "custom"],
        }
        request = Request(f"{self.base_url}/api/langgraph/runs/stream", data=canonical_json(body).encode("utf-8"), headers={"Content-Type": "application/json", **headers}, method="POST")
        try:
            with urlopen(request, timeout=_timeout(spec)) as response:
                raw = response.read(int(spec.get("max_bytes", 512_000)) + 1)
        except (HTTPError, URLError, TimeoutError, OSError) as err:
            raise SidecarAdapterError(f"DeerFlow HTTP request failed: {type(err).__name__}") from err
        if len(raw) > int(spec.get("max_bytes", 512_000)):
            raise SidecarAdapterError("DeerFlow response exceeded the job byte limit")
        payload = dict(_json_from_text(_sse_text(raw)))
        payload.setdefault("schema", "MarketOS.ResearchEvidence.v1")
        payload.setdefault("job_id", spec["job_id"])
        payload.setdefault("runtime", self.name)
        return payload


def build_default_swarm_runtimes() -> dict[str, Callable[[Mapping[str, Any]], Mapping[str, Any]]]:
    """Return sidecar adapters without probing or contacting either runtime."""
    return {"hermes": HermesRuntimeAdapter(), "deerflow": DeerFlowRuntimeAdapter()}


def benchmark_runtimes(spec: SwarmJobSpec, *, runtimes: Mapping[str, Callable[[Mapping[str, Any]], Mapping[str, Any]]] | None = None) -> dict[str, Any]:
    """Run a bounded, flag-gated comparison without persisting evidence."""
    runtimes = runtimes or build_default_swarm_runtimes()
    results: dict[str, Any] = {}
    for runtime_name in ("hermes", "deerflow"):
        if not _flag(f"FF_RESEARCH_SWARM_{runtime_name.upper()}"):
            results[runtime_name] = {"status": "skipped", "reason": "runtime_flag_disabled"}
            continue
        runtime = runtimes.get(runtime_name)
        if runtime is None:
            results[runtime_name] = {"status": "failed", "error_type": "runtime_unavailable"}
            continue
        runtime_spec = replace(spec, runtime=runtime_name)
        started = time.perf_counter()
        try:
            envelope = EvidenceEnvelope.from_mapping(runtime(runtime_spec.to_dict()), runtime_spec)
            results[runtime_name] = {"status": envelope.status, "record_count": len(envelope.records), "rejected_count": len(envelope.rejected), "duration_ms": round((time.perf_counter() - started) * 1000, 2), "envelope_hash": envelope.envelope_hash}
        except Exception as err:
            results[runtime_name] = {"status": "failed", "error_type": type(err).__name__, "duration_ms": round((time.perf_counter() - started) * 1000, 2)}
    return {"benchmark_id": str(uuid.uuid4()), "job_id": spec.job_id, "results": results, "persisted": False}
