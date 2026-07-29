"""Opt-in runtime evaluation for the pinned Medusa sidecar.

The default mode is read-only: it reports the exact evaluation plan and does
not require Docker. Runtime execution is deliberately guarded by both
``--execute`` and ``--teardown`` so a local validation cannot leave commerce
infrastructure running by accident.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).parents[1]
BASE_COMPOSE = ROOT / "docker-compose.yml"
OSS_COMPOSE = ROOT / "docker-compose.oss.example.yml"
PROJECT = "marketos-oss-eval"
Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)


def _commands() -> dict[str, list[str]]:
    compose = ["docker", "compose", "--project-name", PROJECT, "-f", str(BASE_COMPOSE), "-f", str(OSS_COMPOSE)]
    return {
        "config": [*compose, "config", "--quiet"],
        "start": [*compose, "up", "--detach", "--wait", "medusa"],
        "health": [*compose, "exec", "-T", "medusa", "wget", "-q", "-O", "-", "http://127.0.0.1:9000/health"],
        "negative_probe": [*compose, "exec", "-T", "medusa", "wget", "-q", "-O", "-", "http://127.0.0.1:9000/admin/orders/not-a-real-order"],
        "memory": ["docker", "stats", "--no-stream", "--format", "{{json .}}", f"{PROJECT}-medusa-1"],
        "teardown": [*compose, "down", "--volumes", "--remove-orphans"],
    }


def evaluate(*, execute: bool = False, teardown: bool = False, runner: Runner = _run) -> dict[str, object]:
    """Produce a reproducible Medusa validation report.

    The start path only exercises a local Docker sidecar. It neither creates
    carts/orders nor sends requests outside the Docker project.
    """
    commands = _commands()
    report: dict[str, object] = {
        "candidate": "medusa",
        "reviewed_ref": "v2.14.2",
        "base_compose": str(BASE_COMPOSE),
        "oss_compose": str(OSS_COMPOSE),
        "commands": commands,
        "executed": False,
    }
    if execute != teardown:
        report.update(status="blocked", reason="runtime evaluation requires both --execute and --teardown")
        return report
    if not execute:
        report.update(status="planned", reason="pass --execute --teardown to run the isolated local sidecar evaluation")
        return report
    if shutil.which("docker") is None:
        report.update(status="skipped", reason="docker is not installed or not on PATH")
        return report
    if not os.getenv("MEDUSA_IMAGE") or not os.getenv("MEDUSA_DATABASE_URL"):
        report.update(status="blocked", reason="MEDUSA_IMAGE and MEDUSA_DATABASE_URL are required for runtime evaluation")
        return report

    config = runner(commands["config"])
    if config.returncode:
        report.update(status="failed", stage="compose_config", stderr=config.stderr[-4000:])
        return report

    started = time.perf_counter()
    start = runner(commands["start"])
    report["startup_ms"] = round((time.perf_counter() - started) * 1000, 3)
    try:
        if start.returncode:
            report.update(status="failed", stage="start", stderr=start.stderr[-4000:])
            return report
        samples: list[float] = []
        health_payload = ""
        for _ in range(3):
            probe_started = time.perf_counter()
            health = runner(commands["health"])
            samples.append(round((time.perf_counter() - probe_started) * 1000, 3))
            if health.returncode:
                report.update(status="failed", stage="health", stderr=health.stderr[-4000:])
                return report
            health_payload = health.stdout.strip()
        memory = runner(commands["memory"])
        negative = runner(commands["negative_probe"])
        report.update(
            status="passed",
            executed=True,
            health_payload=health_payload,
            health_latency_ms=samples,
            health_latency_p95_ms=max(samples),
            memory=memory.stdout.strip() if memory.returncode == 0 else "unavailable",
            negative_probe_rejected=negative.returncode != 0,
        )
        return report
    finally:
        teardown_result = runner(commands["teardown"])
        report["teardown_returncode"] = teardown_result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="start the isolated local sidecar")
    parser.add_argument("--teardown", action="store_true", help="remove the project after evaluation")
    parser.add_argument("--output", type=Path, help="write JSON report to this path")
    args = parser.parse_args()
    report = evaluate(execute=args.execute, teardown=args.teardown)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0 if report["status"] in {"planned", "passed", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
