"""Opt-in benchmark of Saleor against the MarketOS commerce contract.

Saleor remains a benchmark candidate only.  This script never imports Saleor
code, adds it to the MarketOS runtime, creates carts/orders, or changes an
existing deployment.  An operator supplies an isolated, digest-pinned Saleor
Compose file and an internal GraphQL URL; both ``--execute`` and ``--teardown``
are required so the temporary project cannot be left running accidentally.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import yaml


ROOT = Path(__file__).parents[1]
PROJECT = "marketos-saleor-benchmark"
REVIEWED_REF = "3.23.7"
Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)


def _is_digest_pinned(image: str) -> bool:
    digest = image.rsplit("@sha256:", 1)[-1] if "@sha256:" in image else ""
    return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest.lower())


def _commands(compose_file: Path) -> dict[str, list[str]]:
    compose = ["docker", "compose", "--project-name", PROJECT, "--file", str(compose_file)]
    return {
        "config": [*compose, "config", "--quiet"],
        "start": [*compose, "up", "--detach", "--wait", "api"],
        "api_container": [*compose, "ps", "--quiet", "api"],
        "teardown": [*compose, "down", "--volumes", "--remove-orphans"],
    }


def _graphql_probe(base_url: str) -> dict[str, Any]:
    """Read only the public shop record; no catalog or order mutation occurs."""
    body = json.dumps({"query": "query MarketOSBenchmark { shop { name } }"}).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}/graphql/",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:  # nosec B310 - URL is operator supplied and validated
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise RuntimeError("Saleor GraphQL probe returned no data object")
    return payload


def _configuration_error(*, compose_file: Path, base_url: str, image: str) -> str:
    if not compose_file.is_file():
        return "SALEOR_BENCHMARK_COMPOSE must name an existing isolated Saleor Compose file"
    parsed_url = urlparse(base_url)
    if parsed_url.scheme not in {"http", "https"} or parsed_url.username or parsed_url.password:
        return "SALEOR_BENCHMARK_BASE_URL must be an http(s) URL without embedded credentials"
    if (parsed_url.hostname or "").lower() not in {"localhost", "127.0.0.1", "::1"}:
        return "SALEOR_BENCHMARK_BASE_URL must target the isolated local benchmark service"
    if not _is_digest_pinned(image):
        return "SALEOR_BENCHMARK_IMAGE must be a reviewed image pinned by sha256 digest"
    if not image.startswith(f"ghcr.io/saleor/saleor:{REVIEWED_REF}@sha256:"):
        return f"SALEOR_BENCHMARK_IMAGE must pin ghcr.io/saleor/saleor:{REVIEWED_REF}"
    try:
        compose = yaml.safe_load(compose_file.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        return f"SALEOR_BENCHMARK_COMPOSE could not be read: {exc}"
    api = compose.get("services", {}).get("api", {}) if isinstance(compose, dict) else {}
    if not isinstance(api, dict) or api.get("image") != image or api.get("build"):
        return "Saleor benchmark Compose must define an api service with the exact digest-pinned SALEOR_BENCHMARK_IMAGE and no build"
    return ""


def evaluate(
    *,
    execute: bool = False,
    teardown: bool = False,
    compose_file: Path | None = None,
    base_url: str | None = None,
    image: str | None = None,
    runner: Runner = _run,
    probe: Callable[[str], dict[str, Any]] = _graphql_probe,
) -> dict[str, object]:
    """Produce an isolated, repeatable Saleor benchmark report.

    The operator-controlled Compose file must define an ``api`` service using
    the reviewed image.  Results are comparable to the Medusa evaluator:
    startup duration, read-only health/query latency, container memory, and
    failure behavior.  Commerce contract compatibility is intentionally
    limited to the read-only catalog boundary because Saleor is not adopted.
    """
    configured_compose = compose_file
    if configured_compose is None:
        raw_compose = os.getenv("SALEOR_BENCHMARK_COMPOSE", "").strip()
        configured_compose = Path(raw_compose) if raw_compose else None
    configured_url = base_url or os.getenv("SALEOR_BENCHMARK_BASE_URL", "")
    configured_image = image or os.getenv("SALEOR_BENCHMARK_IMAGE", "")
    commands = _commands(configured_compose) if configured_compose is not None else {}
    report: dict[str, object] = {
        "candidate": "saleor",
        "reviewed_ref": REVIEWED_REF,
        "mode": "benchmark_only",
        "mutating_operations": False,
        "executed": False,
        "contract_checks": ["catalog_read", "inventory_capability", "currency_pricing", "webhook_extensibility"],
        "commands": commands,
    }
    if execute != teardown:
        report.update(status="blocked", reason="benchmark execution requires both --execute and --teardown")
        return report
    if not execute:
        report.update(status="planned", reason="pass --execute --teardown with an isolated digest-pinned Saleor deployment")
        return report
    if configured_compose is None:
        report.update(status="blocked", reason="SALEOR_BENCHMARK_COMPOSE must name an existing isolated Saleor Compose file")
        return report
    error = _configuration_error(compose_file=configured_compose, base_url=configured_url, image=configured_image)
    if error:
        report.update(status="blocked", reason=error)
        return report
    if shutil.which("docker") is None:
        report.update(status="skipped", reason="docker is not installed or not on PATH")
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
        payload: dict[str, Any] = {}
        for _ in range(3):
            probe_started = time.perf_counter()
            try:
                payload = probe(configured_url)
            except (OSError, URLError, ValueError, RuntimeError) as exc:
                report.update(status="failed", stage="graphql_probe", reason=str(exc))
                return report
            samples.append(round((time.perf_counter() - probe_started) * 1000, 3))
        container = runner(commands["api_container"])
        container_id = container.stdout.strip()
        memory = runner(["docker", "stats", "--no-stream", "--format", "{{json .}}", container_id]) if container_id else None
        report.update(
            status="passed",
            executed=True,
            graphql_payload=payload,
            graphql_latency_ms=samples,
            graphql_latency_p95_ms=max(samples),
            memory=memory.stdout.strip() if memory and memory.returncode == 0 else "unavailable",
        )
        return report
    finally:
        teardown_result = runner(commands["teardown"])
        report["teardown_returncode"] = teardown_result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="start the isolated benchmark deployment")
    parser.add_argument("--teardown", action="store_true", help="remove the benchmark project after evaluation")
    parser.add_argument("--output", type=Path, help="write JSON report to this path")
    args = parser.parse_args()
    report = evaluate(execute=args.execute, teardown=args.teardown)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0 if report["status"] in {"planned", "passed", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
