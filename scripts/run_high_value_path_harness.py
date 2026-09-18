#!/usr/bin/env python3
"""Lightweight timing harness for MarketOS high-value dry-run paths.

This is a measurement and classification tool. It is not a second quality gate,
CI authority, orchestrator, or live-provider runner. Missing modules are
``unavailable``, never a silent pass.

Adapted patterns (not vendored):
- Python stdlib ``time.perf_counter`` timing
- FastAPI / Docker dry-run posture already used by ``scripts/benchmark_commerce_cycle.py``
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


PATH_IDS = (
    "product_opportunity_synthesis",
    "unit_economics",
    "supplier_import_normalization",
    "competition_normalization",
    "commerce_dry_run_cycle",
    "report_export_generation",
    "replay_idempotency",
)


def _rss_kb() -> int | None:
    try:
        status = Path("/proc/self/status").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
    return None


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _record(
    path_id: str,
    *,
    status: str,
    input_size: int = 0,
    rows: int = 0,
    wall_ms: float | None = None,
    memory_kb: int | None = None,
    output_fingerprint: str | None = None,
    repeated_match: bool | None = None,
    detail: str = "",
) -> dict[str, Any]:
    return {
        "path_id": path_id,
        "status": status,
        "input_size": input_size,
        "rows": rows,
        "wall_ms": None if wall_ms is None else round(wall_ms, 3),
        "memory_kb": memory_kb,
        "output_fingerprint": output_fingerprint,
        "repeated_match": repeated_match,
        "detail": detail,
    }


def _try_import(module_name: str, attr: str | None = None) -> tuple[Any, str | None]:
    try:
        module = __import__(module_name, fromlist=[attr] if attr else [])
        if attr:
            return getattr(module, attr), None
        return module, None
    except Exception as exc:  # noqa: BLE001 - classification, not swallowing
        return None, f"{type(exc).__name__}: {exc}"


def _time_twice(fn: Callable[[], Any]) -> tuple[Any, Any, float, float]:
    started = time.perf_counter()
    first = fn()
    first_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    second = fn()
    second_ms = (time.perf_counter() - started) * 1000
    return first, second, first_ms, second_ms


def _fixture_unit_economics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic Decimal contribution math used when the kernel is absent.

    This is a measurement fixture only. PR #248 owns the canonical economics
    kernel and must not be forked from this harness.
    """
    results = []
    for row in rows:
        sell = Decimal(str(row["sell"]))
        cost = Decimal(str(row["cost"]))
        ship = Decimal(str(row["ship"]))
        fee = Decimal(str(row["fee_rate"]))
        contribution = (sell - cost - ship - (sell * fee)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )
        results.append(
            {
                "candidate_id": row["candidate_id"],
                "contribution": str(contribution),
                "currency": row["currency"],
                "evidence_state": "fixture",
            }
        )
    return {"rows": results, "schema": "harness-unit-economics-fixture-v1"}


def _fixture_normalize(rows: list[dict[str, Any]], role: str) -> dict[str, Any]:
    accepted = []
    for row in rows:
        candidate = str(row.get("candidate_id") or row.get("sku") or "").strip()
        if not candidate:
            continue
        accepted.append(
            {
                "candidate_id": candidate,
                "role": role,
                "source_type": str(row.get("source_type") or "fixture"),
                "currency": str(row.get("currency") or "MXN").upper(),
            }
        )
    return {"role": role, "accepted": accepted, "count": len(accepted)}


def measure_unit_economics() -> dict[str, Any]:
    rows = [
        {"candidate_id": "sku-a", "sell": "499.00", "cost": "180.00", "ship": "45.00", "fee_rate": "0.034", "currency": "MXN"},
        {"candidate_id": "sku-b", "sell": "799.00", "cost": "310.00", "ship": "55.00", "fee_rate": "0.034", "currency": "MXN"},
    ]
    kernel, err = _try_import("backend.economics.kernel", "calculate_unit_economics")
    if kernel is None:
        runner = lambda: _fixture_unit_economics(rows)
        detail = f"canonical kernel unavailable ({err}); fixture math used"
        status_ok = "measured_fixture"
    else:
        return _record(
            "unit_economics",
            status="skipped_kernel_present_unwired",
            input_size=len(json.dumps(rows)),
            rows=len(rows),
            detail="backend.economics.kernel is present; use that PR's tests rather than this fixture",
        )
    first, second, first_ms, _second_ms = _time_twice(runner)
    fp1, fp2 = _fingerprint(first), _fingerprint(second)
    return _record(
        "unit_economics",
        status=status_ok,
        input_size=len(json.dumps(rows)),
        rows=len(rows),
        wall_ms=first_ms,
        memory_kb=_rss_kb(),
        output_fingerprint=fp1,
        repeated_match=fp1 == fp2,
        detail=detail,
    )


def measure_supplier_import() -> dict[str, Any]:
    rows = [
        {"candidate_id": "sku-a", "sku": "A-1", "source_type": "manual_csv_import", "currency": "MXN"},
        {"candidate_id": "sku-b", "sku": "B-1", "source_type": "manual_csv_import", "currency": "MXN"},
        {"sku": "", "source_type": "manual_csv_import"},
    ]
    importer, err = _try_import("backend.adapters.research.supplier_feasibility", "import_json")
    if importer is None:
        first, second, first_ms, _ = _time_twice(lambda: _fixture_normalize(rows, "supplier"))
        fp1, fp2 = _fingerprint(first), _fingerprint(second)
        return _record(
            "supplier_import_normalization",
            status="measured_fixture",
            input_size=len(json.dumps(rows)),
            rows=len(rows),
            wall_ms=first_ms,
            memory_kb=_rss_kb(),
            output_fingerprint=fp1,
            repeated_match=fp1 == fp2,
            detail=f"adapter unavailable ({err}); fixture normalizer used",
        )
    return _record(
        "supplier_import_normalization",
        status="unavailable_live_adapter_not_invoked",
        input_size=len(json.dumps(rows)),
        rows=len(rows),
        detail="adapter imported; file-based import is not invoked without an operator fixture path",
    )


def measure_competition() -> dict[str, Any]:
    rows = [
        {"candidate_id": "sku-a", "source_type": "observation", "currency": "MXN"},
        {"candidate_id": "sku-b", "source_type": "observation", "currency": "MXN"},
    ]
    first, second, first_ms, _ = _time_twice(lambda: _fixture_normalize(rows, "competition"))
    fp1, fp2 = _fingerprint(first), _fingerprint(second)
    return _record(
        "competition_normalization",
        status="measured_fixture",
        input_size=len(json.dumps(rows)),
        rows=len(rows),
        wall_ms=first_ms,
        memory_kb=_rss_kb(),
        output_fingerprint=fp1,
        repeated_match=fp1 == fp2,
        detail="competition path measured via fixture normalizer; live adapters stay uncalled",
    )


def measure_opportunity_synthesis() -> dict[str, Any]:
    builder, err = _try_import("evaluation.commerce.opportunity_synthesis", "build_product_opportunity_synthesis")
    if builder is None:
        return _record(
            "product_opportunity_synthesis",
            status="unavailable",
            detail=err or "module missing",
        )
    return _record(
        "product_opportunity_synthesis",
        status="not_run",
        detail="module present; invocation reserved for operator-local fixtures (no invented candidates)",
    )


def measure_commerce_cycle() -> dict[str, Any]:
    runner, err = _try_import("backend.commerce", "run_commerce_cycle")
    if runner is None:
        return _record(
            "commerce_dry_run_cycle",
            status="unavailable",
            detail=err or "module missing",
        )
    return _record(
        "commerce_dry_run_cycle",
        status="not_run",
        detail="use scripts/benchmark_commerce_cycle.py in a full checkout; harness does not start inference",
    )


def measure_report_export() -> dict[str, Any]:
    generator, err = _try_import("evaluation.commerce.product_validation_report", "generate")
    if generator is None:
        payload = {"schema": "harness-export-v1", "status": "draft", "authority": "none"}
        first, second, first_ms, _ = _time_twice(lambda: dict(payload))
        fp1, fp2 = _fingerprint(first), _fingerprint(second)
        return _record(
            "report_export_generation",
            status="measured_fixture",
            input_size=len(json.dumps(payload)),
            rows=1,
            wall_ms=first_ms,
            memory_kb=_rss_kb(),
            output_fingerprint=fp1,
            repeated_match=fp1 == fp2,
            detail=f"report generator unavailable ({err}); draft fixture only",
        )
    return _record(
        "report_export_generation",
        status="not_run",
        detail="generator present; use scripts/generate_product_validation_report.py with fixtures",
    )


def measure_replay() -> dict[str, Any]:
    packet = {"lane": "MXN-home", "candidates": ["sku-a", "sku-b"], "dry_run": True}
    first, second, first_ms, _ = _time_twice(lambda: {"fingerprint": _fingerprint(packet), "replay": True})
    fp1, fp2 = _fingerprint(first), _fingerprint(second)
    return _record(
        "replay_idempotency",
        status="measured_fixture",
        input_size=len(json.dumps(packet)),
        rows=2,
        wall_ms=first_ms,
        memory_kb=_rss_kb(),
        output_fingerprint=fp1,
        repeated_match=fp1 == fp2,
        detail="SHA-256 replay fingerprint is stable across two in-process runs",
    )


def inspect_container_files(root: Path | None = None) -> dict[str, Any]:
    base = root or ROOT

    def _active_lines(text: str) -> str:
        lines = []
        for raw in text.splitlines():
            stripped = raw.split("#", 1)[0].strip()
            if stripped:
                lines.append(stripped)
        return "\n".join(lines)

    dockerfile = (base / "Dockerfile").read_text(encoding="utf-8") if (base / "Dockerfile").exists() else ""
    compose = (base / "docker-compose.prod.yml").read_text(encoding="utf-8") if (base / "docker-compose.prod.yml").exists() else ""
    python_version = (base / ".python-version").read_text(encoding="utf-8").strip() if (base / ".python-version").exists() else ""
    dockerfile_active = _active_lines(dockerfile)
    compose_active = _active_lines(compose)
    return {
        "python_version_file": python_version,
        "dockerfile_from_312": "FROM python:3.12-slim" in dockerfile,
        "dockerfile_non_root": "USER marketos" in dockerfile,
        "dockerfile_healthcheck": "HEALTHCHECK" in dockerfile,
        "dockerfile_no_reload": "--reload" not in dockerfile_active,
        "compose_prod_no_host_postgres_publish": "5432:5432" not in compose,
        "compose_prod_requires_password": "POSTGRES_PASSWORD" in compose,
        "compose_prod_healthcheck": "healthcheck:" in compose,
        "compose_prod_no_reload": "--reload" not in compose_active,
    }


def run_harness() -> dict[str, Any]:
    measurements = [
        measure_opportunity_synthesis(),
        measure_unit_economics(),
        measure_supplier_import(),
        measure_competition(),
        measure_commerce_cycle(),
        measure_report_export(),
        measure_replay(),
    ]
    return {
        "schema": "MarketOS.HighValuePathHarness.v1",
        "live_actions": False,
        "quality_gate": "not_this_script",
        "container": inspect_container_files(),
        "measurements": measurements,
        "summary": {
            "measured": sum(1 for item in measurements if str(item["status"]).startswith("measured")),
            "unavailable": sum(1 for item in measurements if item["status"] == "unavailable"),
            "not_run": sum(1 for item in measurements if item["status"] == "not_run"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_harness()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"schema={report['schema']} live_actions={report['live_actions']}")
        for item in report["measurements"]:
            print(f"{item['path_id']}: {item['status']} wall_ms={item['wall_ms']} repeat={item['repeated_match']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
