"""backend.orchestration.workflow — Step/Workflow engine with DAG + compensation.

A Workflow is an ordered list of Steps. Each Step declares:

  - ``fn(ctx)``       — the work; receives a context dict of prior outputs
  - ``depends_on``    — names of steps whose success it requires
  - ``required``      — if True, its failure fails the workflow (after
                        compensating already-completed steps that define
                        ``compensate``); if False, the step records a
                        fallback value and execution continues
  - ``compensate(ctx, output)`` — undo logic invoked in reverse completion
                        order when a later required step fails
  - ``validate(ctx)`` — extra gate beyond dependency success (e.g. "metrics
                        are fresh"); returning False skips the step

Dependency semantics fix the stale-data cascade: a step whose dependency
failed or was skipped is itself skipped (never run on missing inputs),
recorded as such in the event store, and — if required — fails the workflow.

Every state change is journaled through the EventStore *before* the
workflow returns, so the invariant "started implies eventually terminal,
or visible as incomplete after a crash" holds.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.orchestration.event_store import EventStore, event_store, new_workflow_id

_log = logging.getLogger(__name__)


@dataclass
class Step:
    name: str
    fn: Callable[[dict], Any]
    depends_on: tuple[str, ...] = ()
    required: bool = True
    fallback: Any = None
    timeout_s: float | None = None          # advisory; recorded in events
    compensate: Callable[[dict, Any], None] | None = None
    validate: Callable[[dict], bool] | None = None


@dataclass
class StepResult:
    name: str
    status: str                  # "ok" | "failed" | "skipped"
    output: Any = None
    error: str | None = None
    reason: str | None = None    # skip reason
    duration_s: float = 0.0


@dataclass
class WorkflowResult:
    workflow_id: str
    status: str                  # "ok" | "failed"
    steps: dict[str, StepResult] = field(default_factory=dict)
    compensated: list[str] = field(default_factory=list)

    @property
    def context(self) -> dict[str, Any]:
        return {n: r.output for n, r in self.steps.items() if r.status == "ok"}


class Workflow:
    def __init__(self, name: str, steps: list[Step],
                 store: EventStore | None = None):
        self.name = name
        self.steps = steps
        self.store = store or event_store
        self._check_dag()

    def _check_dag(self) -> None:
        seen: set[str] = set()
        for s in self.steps:
            missing = [d for d in s.depends_on if d not in seen]
            if missing:
                raise ValueError(
                    f"step '{s.name}' depends on {missing} which are not "
                    "defined earlier in the workflow (steps run in list order)")
            seen.add(s.name)

    # ── execution ────────────────────────────────────────────────────────

    def run(self, initial_context: dict[str, Any] | None = None,
            workflow_id: str | None = None) -> WorkflowResult:
        wid = workflow_id or new_workflow_id(self.name)
        ctx: dict[str, Any] = dict(initial_context or {})
        result = WorkflowResult(workflow_id=wid, status="ok")
        completed: list[Step] = []

        self.store.append(wid, "workflow_started", workflow=self.name,
                          data={"steps": [s.name for s in self.steps]})

        for step in self.steps:
            sr = self._run_step(wid, step, ctx, result)
            result.steps[step.name] = sr
            if sr.status == "ok":
                ctx[step.name] = sr.output
                completed.append(step)
            elif step.required:
                # Required step failed/skipped → compensate and fail.
                self._compensate(wid, completed, ctx, result)
                result.status = "failed"
                self.store.append(wid, "workflow_failed", workflow=self.name,
                                  data={"failed_step": step.name,
                                        "error": sr.error or sr.reason})
                return result
            # Optional step failure: fallback recorded, keep going.

        self.store.append(wid, "workflow_completed", workflow=self.name,
                          data={"steps_ok": [s.name for s in completed]})
        return result

    def _run_step(self, wid: str, step: Step, ctx: dict,
                  result: WorkflowResult) -> StepResult:
        # Dependency gate — never run a step on missing/failed inputs.
        for dep in step.depends_on:
            dep_res = result.steps.get(dep)
            if dep_res is None or dep_res.status != "ok":
                reason = f"dependency_{dep}_{dep_res.status if dep_res else 'missing'}"
                self.store.append(wid, "step_failed", workflow=self.name,
                                  step=step.name, data={"reason": reason})
                _log.warning("step_skipped workflow=%s step=%s reason=%s",
                             self.name, step.name, reason)
                return StepResult(step.name, "skipped", output=step.fallback,
                                  reason=reason)

        # Validation gate (e.g. data freshness).
        if step.validate is not None:
            try:
                valid = bool(step.validate(ctx))
            except Exception as exc:
                valid = False
                _log.warning("step_validate_error step=%s error=%s",
                             step.name, exc)
            if not valid:
                self.store.append(wid, "step_failed", workflow=self.name,
                                  step=step.name,
                                  data={"reason": "validation_failed"})
                return StepResult(step.name, "skipped", output=step.fallback,
                                  reason="validation_failed")

        self.store.append(wid, "step_started", workflow=self.name,
                          step=step.name, data={"timeout_s": step.timeout_s})
        t0 = time.time()
        try:
            output = step.fn(ctx)
        except Exception as exc:
            dur = time.time() - t0
            self.store.append(wid, "step_failed", workflow=self.name,
                              step=step.name,
                              data={"error": str(exc), "duration_s": dur})
            _log.exception("step_failed workflow=%s step=%s", self.name, step.name)
            return StepResult(step.name, "failed", output=step.fallback,
                              error=str(exc), duration_s=dur)

        dur = time.time() - t0
        self.store.append(wid, "step_completed", workflow=self.name,
                          step=step.name,
                          data={"output": _jsonable(output), "duration_s": dur})
        return StepResult(step.name, "ok", output=output, duration_s=dur)

    def _compensate(self, wid: str, completed: list[Step], ctx: dict,
                    result: WorkflowResult) -> None:
        """Undo completed steps in reverse order; a failing compensation is
        logged and skipped — never masks the original failure."""
        for step in reversed(completed):
            if step.compensate is None:
                continue
            try:
                step.compensate(ctx, ctx.get(step.name))
                result.compensated.append(step.name)
                self.store.append(wid, "step_compensated", workflow=self.name,
                                  step=step.name)
            except Exception as exc:
                _log.exception("compensation_failed workflow=%s step=%s",
                               self.name, step.name)
                self.store.append(wid, "step_failed", workflow=self.name,
                                  step=step.name,
                                  data={"reason": "compensation_failed",
                                        "error": str(exc)})


def _jsonable(value: Any) -> Any:
    """Best-effort conversion so event payloads always serialize."""
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)


__all__ = ["Step", "StepResult", "Workflow", "WorkflowResult"]
