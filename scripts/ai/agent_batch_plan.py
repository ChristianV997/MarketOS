"""Pre-dispatch validator for agent batch plans (``MarketOS.AgentBatchPlan.v1``).

Checks a JSON plan before any agent starts: one assignment per roster agent,
the policy's batch order and sizes, unique task and prompt identifiers,
canonical repository-relative write scopes with no overlap between agents,
and an acyclic dependency graph. It reads only the plan and the policy file.
It never dispatches work, reads credentials, calls a provider or host, or
changes git state. Post-run handoff evidence is audited by
``agent_output_eval.audit_handoff_batch`` instead.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.ai.operator_task_packet import SECRET_KEY_HINT, SECRET_SHAPED, _in_scope

SCHEMA = "MarketOS.AgentBatchPlan.v1"
POLICY_SCHEMA = "MarketOS.AgentBatchPolicy.v1"
REPORT_SCHEMA = "MarketOS.AgentBatchPlanReport.v1"
POLICY_PATH = Path(__file__).resolve().with_name("agent_batch_policy.json")
MAX_MANIFEST_BYTES = 65_536
MAX_POLICY_BYTES = 16_384
MAX_DEPTH = 8
MAX_LIST_ITEMS = 16
MAX_PATH_CHARS = 240
MAX_REPORTED_ERRORS = 64
MAX_REPORTED_PATHS = 8
ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_DRIVE = re.compile(r"[A-Za-z]:")
_TOP_KEYS = frozenset({"schema", "session_id", "batches"})
_BATCH_KEYS = frozenset({"batch", "assignments"})
_ASSIGNMENT_KEYS = frozenset({"agent_id", "task_id", "prompt_id", "primary_paths", "fallback_paths", "depends_on"})
_REQUIRED_ASSIGNMENT_KEYS = frozenset({"agent_id", "task_id", "prompt_id", "primary_paths", "fallback_paths"})
_POLICY_KEYS = frozenset(
    {
        "schema",
        "policy_id",
        "require_earlier_batch_dependencies",
        "forbidden_segments",
        "forbidden_segment_prefixes",
        "batches",
    }
)
_POLICY_BATCH_KEYS = frozenset({"batch", "size", "agents"})
_KNOWN_KEYS = _TOP_KEYS | _BATCH_KEYS | _ASSIGNMENT_KEYS


class PlanError(ValueError):
    """Sanitized failure. ``code`` is a fixed identifier, never raw input text."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _DuplicateKey(ValueError):
    """Raised inside the JSON object hook so a repeated key is never overwritten silently."""


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _reject_constant(name: str) -> Any:
    raise ValueError(name)


def _parse_json(raw: bytes, limit: int, prefix: str) -> Any:
    if len(raw) > limit:
        raise PlanError(f"{prefix}_too_large")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_keys, parse_constant=_reject_constant)
    except _DuplicateKey:
        raise PlanError(f"{prefix}_duplicate_key") from None
    except (ValueError, RecursionError):
        raise PlanError(f"{prefix}_malformed") from None


def _finding(code: str, location: str, **extra: Any) -> dict[str, Any]:
    item: dict[str, Any] = {"code": code, "location": location}
    for key, value in extra.items():
        if value:
            item[key] = value
    return item


def _is_int(value: Any, expected: int) -> bool:
    return type(value) is int and value == expected


def _too_deep(value: Any, limit: int) -> bool:
    pending: list[tuple[Any, int]] = [(value, 1)]
    while pending:
        item, depth = pending.pop()
        if depth > limit:
            return True
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return False


def _label(location: str, key: str) -> str:
    """Child location for a key. Unknown key names are never echoed."""
    name = key if key in _KNOWN_KEYS else "<unknown>"
    return f"{location}.{name}" if location else name


def _sweep_sensitive(value: Any, location: str, findings: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if SECRET_KEY_HINT.search(key.replace("-", "_")):
                findings.append(_finding("sensitive_field", location))
            _sweep_sensitive(item, _label(location, key), findings)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _sweep_sensitive(item, f"{location}[{index}]", findings)
    elif isinstance(value, str) and SECRET_SHAPED.search(value):
        findings.append(_finding("sensitive_value", location))


def _unknown_keys(item: dict[str, Any], allowed: frozenset[str], location: str, findings: list[dict[str, Any]]) -> None:
    for key in item:
        # A secret-shaped key is reported once by the sensitive sweep, not again here.
        if key not in allowed and not SECRET_KEY_HINT.search(key.replace("-", "_")):
            findings.append(_finding("unknown_field", location))
            return


def _id_value(value: Any, location: str, findings: list[dict[str, Any]]) -> str | None:
    if isinstance(value, str) and SECRET_SHAPED.search(value):
        return None
    if not isinstance(value, str):
        findings.append(_finding("invalid_type", location))
        return None
    if not ID_PATTERN.fullmatch(value):
        findings.append(_finding("invalid_identifier", location))
        return None
    return value


def _path_code(value: str, policy: dict[str, Any]) -> str | None:
    """Stable code for an unsafe or non-canonical scope path, or None when it is canonical."""
    if not value or len(value) > MAX_PATH_CHARS:
        return "invalid_path"
    if value.startswith("/") or _DRIVE.match(value):
        return "path_absolute"
    if _CONTROL.search(value) or ":" in value:
        return "invalid_path"
    if "\\" in value or value != value.strip():
        return "path_not_normalized"
    parts = value.split("/")
    if ".." in parts:
        return "path_traversal"
    if value.endswith("/") or any(part in ("", ".") for part in parts):
        return "path_not_normalized"
    for part in parts:
        if part in policy["forbidden_segments"] or part.startswith(tuple(policy["forbidden_segment_prefixes"])):
            return "forbidden_path"
    return None


def _scope_list(
    item: dict[str, Any],
    key: str,
    location: str,
    policy: dict[str, Any],
    findings: list[dict[str, Any]],
    *,
    required: bool,
) -> list[str]:
    if key not in item:
        return []
    where = f"{location}.{key}"
    value = item[key]
    if not isinstance(value, list):
        findings.append(_finding("invalid_type", where))
        return []
    if len(value) > MAX_LIST_ITEMS:
        findings.append(_finding("too_many_items", where))
        return []
    if required and not value:
        findings.append(_finding("empty_scope", where))
    valid: list[str] = []
    for index, raw in enumerate(value):
        raw_location = f"{where}[{index}]"
        if not isinstance(raw, str):
            findings.append(_finding("invalid_type", raw_location))
        elif SECRET_SHAPED.search(raw):
            continue
        elif (code := _path_code(raw, policy)) is not None:
            findings.append(_finding(code, raw_location))
        elif raw in valid:
            findings.append(_finding("duplicate_path", raw_location, paths=[raw]))
        else:
            valid.append(raw)
    return valid


def _dependency_list(item: dict[str, Any], location: str, findings: list[dict[str, Any]]) -> list[str]:
    if "depends_on" not in item:
        return []
    where = f"{location}.depends_on"
    value = item["depends_on"]
    if not isinstance(value, list):
        findings.append(_finding("invalid_type", where))
        return []
    if len(value) > MAX_LIST_ITEMS:
        findings.append(_finding("too_many_items", where))
        return []
    depends: list[str] = []
    for index, raw in enumerate(value):
        dep = _id_value(raw, f"{where}[{index}]", findings)
        if dep is None:
            continue
        if dep in depends:
            findings.append(_finding("duplicate_dependency", f"{where}[{index}]", ids=[dep]))
        else:
            depends.append(dep)
    return depends


def _check_assignment(
    item: Any,
    location: str,
    batch_number: int,
    policy: dict[str, Any],
    findings: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        findings.append(_finding("invalid_type", location))
        return None
    _unknown_keys(item, _ASSIGNMENT_KEYS, location, findings)
    for key in sorted(_REQUIRED_ASSIGNMENT_KEYS - set(item)):
        findings.append(_finding("missing_field", f"{location}.{key}"))
    agent = _id_value(item["agent_id"], f"{location}.agent_id", findings) if "agent_id" in item else None
    task = _id_value(item["task_id"], f"{location}.task_id", findings) if "task_id" in item else None
    prompt = _id_value(item["prompt_id"], f"{location}.prompt_id", findings) if "prompt_id" in item else None
    if agent is not None:
        if agent not in policy["agent_batch"]:
            findings.append(_finding("unknown_agent", f"{location}.agent_id"))
        elif policy["agent_batch"][agent] != batch_number:
            findings.append(_finding("agent_wrong_batch", f"{location}.agent_id", agents=[agent]))
    return {
        "location": location,
        "batch": batch_number,
        "agent": agent,
        "task": task,
        "prompt": prompt,
        "primary": _scope_list(item, "primary_paths", location, policy, findings, required=True),
        "fallback": _scope_list(item, "fallback_paths", location, policy, findings, required=False),
        "depends": _dependency_list(item, location, findings),
    }


def _check_batch(
    batch: Any,
    index: int,
    expected: dict[str, Any],
    policy: dict[str, Any],
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    location = f"batches[{index}]"
    if not isinstance(batch, dict):
        findings.append(_finding("invalid_type", location))
        return []
    _unknown_keys(batch, _BATCH_KEYS, location, findings)
    if "batch" not in batch:
        findings.append(_finding("missing_field", f"{location}.batch"))
    elif not _is_int(batch["batch"], expected["batch"]):
        findings.append(_finding("batch_order_mismatch", f"{location}.batch"))
    if "assignments" not in batch:
        findings.append(_finding("missing_field", f"{location}.assignments"))
        return []
    assignments = batch["assignments"]
    if not isinstance(assignments, list):
        findings.append(_finding("invalid_type", f"{location}.assignments"))
        return []
    if len(assignments) != expected["size"]:
        findings.append(_finding("batch_size_mismatch", f"{location}.assignments"))
    records: list[dict[str, Any]] = []
    # Only the policy's slots are checked in detail. Extra entries still fail batch_size_mismatch
    # and the sensitive sweep covers them, so the pairwise overlap check stays bounded by the roster.
    for slot, item in enumerate(assignments[: expected["size"]]):
        record = _check_assignment(item, f"{location}.assignments[{slot}]", expected["batch"], policy, findings)
        if record is not None:
            records.append(record)
    return records


def _check_unique(records: list[dict[str, Any]], field: str, code: str, findings: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for record in records:
        value = record[field]
        if value is None:
            continue
        if value in seen:
            findings.append(_finding(code, f"{record['location']}.{field}_id", ids=[value]))
        seen.add(value)


def _overlaps(left: str, right: str) -> bool:
    # Equal paths, or one path inside the other's directory. The "/" boundary comes from
    # _in_scope, so "shared" and "shared2" do not overlap.
    return left == right or _in_scope(left, [right]) or _in_scope(right, [left])


def _overlap_code(left_kind: str, right_kind: str) -> str:
    if left_kind == right_kind == "primary":
        return "primary_primary_overlap"
    if left_kind == right_kind == "fallback":
        return "fallback_fallback_overlap"
    return "primary_fallback_overlap"


def _check_overlaps(records: list[dict[str, Any]], findings: list[dict[str, Any]]) -> None:
    """Compare write scopes across different agents. Same-agent pairs are duplicate-assignment findings.

    One finding per agent pair and overlap code, so a shared scope cannot inflate the report. ``overlap_count``
    keeps the number of overlapping path combinations, and ``paths`` lists at most MAX_REPORTED_PATHS of them.
    """
    for left_index, left in enumerate(records):
        for right in records[left_index + 1 :]:
            if left["agent"] and left["agent"] == right["agent"]:
                continue
            agents = sorted(agent for agent in (left["agent"], right["agent"]) if agent)
            location = f"{left['location']} / {right['location']}"
            grouped: dict[str, dict[str, Any]] = {}
            for left_kind in ("primary", "fallback"):
                for right_kind in ("primary", "fallback"):
                    code = _overlap_code(left_kind, right_kind)
                    for left_path in left[left_kind]:
                        for right_path in right[right_kind]:
                            if _overlaps(left_path, right_path):
                                bucket = grouped.setdefault(code, {"paths": set(), "count": 0})
                                bucket["paths"].update((left_path, right_path))
                                bucket["count"] += 1
            for code in sorted(grouped):
                bucket = grouped[code]
                findings.append(
                    _finding(
                        code,
                        location,
                        agents=agents,
                        paths=sorted(bucket["paths"])[:MAX_REPORTED_PATHS],
                        overlap_count=bucket["count"],
                    )
                )


def _cycle_members(tasks: list[str], edges: dict[str, list[str]]) -> list[str]:
    """Tasks that sit on a dependency cycle. Tasks that only wait on a cycle are not named."""
    # Prune tasks whose dependencies are all resolved. What survives is a cycle or waits on one.
    remaining = set(tasks)
    shrinking = True
    while shrinking:
        shrinking = False
        for task in sorted(remaining):
            if not any(dep in remaining for dep in edges.get(task, [])):
                remaining.discard(task)
                shrinking = True
    members: list[str] = []
    for task in sorted(remaining):
        pending = list(edges.get(task, []))
        seen: set[str] = set()
        while pending:
            node = pending.pop()
            if node == task:
                members.append(task)
                break
            if node in remaining and node not in seen:
                seen.add(node)
                pending.extend(edges.get(node, []))
    return members


def _check_dependencies(records: list[dict[str, Any]], policy: dict[str, Any], findings: list[dict[str, Any]]) -> None:
    by_task: dict[str, dict[str, Any]] = {}
    for record in records:
        if record["task"] and record["task"] not in by_task:
            by_task[record["task"]] = record
    edges: dict[str, list[str]] = {}
    for record in records:
        task = record["task"]
        if not task or by_task[task] is not record:
            continue
        where = f"{record['location']}.depends_on"
        for dep in record["depends"]:
            if dep == task:
                findings.append(_finding("dependency_self", where, ids=[task]))
            elif dep not in by_task:
                findings.append(_finding("unknown_dependency", where, ids=[dep]))
            else:
                if policy["require_earlier_batch_dependencies"] and by_task[dep]["batch"] >= record["batch"]:
                    findings.append(_finding("dependency_not_earlier_batch", where, ids=sorted({task, dep})))
                edges.setdefault(task, []).append(dep)
    cycle = _cycle_members(list(by_task), edges)
    if cycle:
        findings.append(_finding("dependency_cycle", "batches", ids=cycle))


def _report(
    policy_id: str | None, findings: list[dict[str, Any]], session_id: str | None, checked: int
) -> dict[str, Any]:
    unique = {json.dumps(item, sort_keys=True): item for item in findings}
    ordered = sorted(
        unique.values(), key=lambda item: (item["code"], item["location"], json.dumps(item, sort_keys=True))
    )
    # error_count and valid always describe the full set; only the listed errors are capped.
    return {
        "schema": REPORT_SCHEMA,
        "policy_id": policy_id,
        "read_only": True,
        "valid": not ordered,
        "error_count": len(ordered),
        "truncated": len(ordered) > MAX_REPORTED_ERRORS,
        "errors": ordered[:MAX_REPORTED_ERRORS],
        "session_id": session_id,
        "assignments_checked": checked,
    }


def failure_report(code: str, location: str = "", policy_id: str | None = None) -> dict[str, Any]:
    """Report for a failure that happens before the plan itself is checked."""
    return _report(policy_id, [_finding(code, location)], None, 0)


def validate_plan_object(plan_obj: Any, policy: dict[str, Any]) -> dict[str, Any]:
    """Validate an already-parsed plan against a normalized policy from ``load_policy``."""
    if _too_deep(plan_obj, MAX_DEPTH):
        return failure_report("manifest_too_deep", "", policy["policy_id"])
    findings: list[dict[str, Any]] = []
    _sweep_sensitive(plan_obj, "", findings)
    if not isinstance(plan_obj, dict):
        findings.append(_finding("manifest_not_object", ""))
        return _report(policy["policy_id"], findings, None, 0)
    _unknown_keys(plan_obj, _TOP_KEYS, "", findings)
    for key in sorted(_TOP_KEYS - set(plan_obj)):
        findings.append(_finding("missing_field", key))
    if "schema" in plan_obj and plan_obj["schema"] != SCHEMA:
        findings.append(_finding("schema_mismatch", "schema"))
    session_id = _id_value(plan_obj["session_id"], "session_id", findings) if "session_id" in plan_obj else None
    records: list[dict[str, Any]] = []
    batches_ok = False
    if "batches" in plan_obj:
        batches = plan_obj["batches"]
        if isinstance(batches, list):
            batches_ok = True
            expected = policy["batches"]
            if len(batches) != len(expected):
                findings.append(_finding("batch_count_mismatch", "batches"))
            for index, batch in enumerate(batches[: len(expected)]):
                records.extend(_check_batch(batch, index, expected[index], policy, findings))
        else:
            findings.append(_finding("invalid_type", "batches"))
    _check_unique(records, "task", "duplicate_task_id", findings)
    _check_unique(records, "prompt", "duplicate_prompt_id", findings)
    if batches_ok:
        counts = Counter(record["agent"] for record in records if record["agent"])
        for agent in sorted(name for name, count in counts.items() if count > 1):
            findings.append(_finding("duplicate_agent_assignment", "batches", agents=[agent]))
        for agent in policy["agents"]:
            if agent not in counts:
                findings.append(_finding("missing_agent", "batches", agents=[agent]))
    _check_overlaps(records, findings)
    _check_dependencies(records, policy, findings)
    return _report(policy["policy_id"], findings, session_id, len(records))


def validate_plan_bytes(raw: bytes, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Parse a size-capped plan from raw bytes and validate it. Never raises on bad input."""
    active = load_policy() if policy is None else policy
    try:
        plan_obj = _parse_json(raw, MAX_MANIFEST_BYTES, "manifest")
    except PlanError as exc:
        return failure_report(exc.code, "", active["policy_id"])
    return validate_plan_object(plan_obj, active)


def _policy_strings(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item and "/" not in item and item == item.strip() for item in value
    ):
        raise PlanError("policy_invalid")
    return list(value)


def _normalize_policy(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or set(data) != _POLICY_KEYS or data["schema"] != POLICY_SCHEMA:
        raise PlanError("policy_invalid")
    policy_id = data["policy_id"]
    if not isinstance(policy_id, str) or not ID_PATTERN.fullmatch(policy_id):
        raise PlanError("policy_invalid")
    earlier = data["require_earlier_batch_dependencies"]
    if type(earlier) is not bool:
        raise PlanError("policy_invalid")
    segments = _policy_strings(data["forbidden_segments"])
    prefixes = _policy_strings(data["forbidden_segment_prefixes"])
    entries = data["batches"]
    if not isinstance(entries, list) or not entries:
        raise PlanError("policy_invalid")
    batches: list[dict[str, Any]] = []
    agent_batch: dict[str, int] = {}
    for position, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict) or set(entry) != _POLICY_BATCH_KEYS:
            raise PlanError("policy_invalid")
        if not _is_int(entry["batch"], position):
            raise PlanError("policy_batch_order")
        agents = entry["agents"]
        if not isinstance(agents, list) or not agents:
            raise PlanError("policy_invalid")
        if not _is_int(entry["size"], len(agents)):
            raise PlanError("policy_size_mismatch")
        for agent in agents:
            if not isinstance(agent, str) or not ID_PATTERN.fullmatch(agent) or agent in agent_batch:
                raise PlanError("policy_invalid")
            agent_batch[agent] = position
        batches.append({"batch": position, "size": len(agents), "agents": list(agents)})
    return {
        "policy_id": policy_id,
        "require_earlier_batch_dependencies": earlier,
        "forbidden_segments": segments,
        "forbidden_segment_prefixes": prefixes,
        "batches": batches,
        "agents": [agent for batch in batches for agent in batch["agents"]],
        "agent_batch": agent_batch,
    }


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    """Load and self-check the roster policy. Raises ``PlanError`` with a stable code."""
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_POLICY_BYTES + 1)
    except OSError:
        raise PlanError("policy_unreadable") from None
    return _normalize_policy(_parse_json(raw, MAX_POLICY_BYTES, "policy"))
