"""Run the offline MarketOS commerce-operations readiness cycle."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.commerce.commerce_operations_cycle import (  # noqa: E402
    GENERATED_AT,
    build_commerce_operations_cycle,
    reject_unsafe_input,
)
from scripts.run_product_opportunity_synthesis import _default_reports  # noqa: E402

MAX_BATCH_JOBS = 8
BATCH_REPORT_VERSION = "commerce-operations-cycle-batch-v1"
JOB_PATH_KEYS = (
    "marketplace_trend_report",
    "supplier_feasibility_report",
    "consumer_attention_report",
)
JOB_PATH_LABELS = {
    "marketplace_trend_report": "marketplace report",
    "supplier_feasibility_report": "supplier report",
    "consumer_attention_report": "consumer report",
}
OUTPUT_REPORT_JSON = "commerce_operations_cycle_report.json"
OUTPUT_REPORT_MD = "commerce_operations_cycle_report.md"
OUTPUT_PROJECTION = "client_safe_projection.json"
BATCH_SUMMARY_NAME = "batch_summary.json"


def _path_is_unsafe(path: str) -> bool:
    target = Path(path)
    path_parts = path.replace("\\", "/").split("/")
    return ".." in target.parts or ".." in path_parts or target.suffix.lower() != ".json"


def _output_is_unsafe(directory: str) -> bool:
    target = Path(directory)
    return ".." in target.parts or ".." in directory.replace("\\", "/").split("/")


def _job_id_is_safe(job_id: str) -> bool:
    if not job_id or job_id in {".", ".."}:
        return False
    if "/" in job_id or "\\" in job_id or ".." in job_id:
        return False
    if job_id.startswith("."):
        return False
    return True


def _read(path: str | None, *, label: str) -> dict[str, Any] | None:
    if not path:
        return None
    target = Path(path)
    if _path_is_unsafe(path):
        raise ValueError("only local JSON report paths without traversal are supported")
    if not target.is_file():
        raise ValueError(f"{label} does not exist: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed JSON in {label}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    reject_unsafe_input(value, label=label)
    return value


def _write_output(directory: str, report: dict[str, Any], markdown_text: str) -> None:
    target = Path(directory)
    if _output_is_unsafe(directory):
        raise ValueError("output traversal is not allowed")
    target.mkdir(parents=True, exist_ok=True)
    (target / OUTPUT_REPORT_JSON).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf8"
    )
    (target / OUTPUT_REPORT_MD).write_text(markdown_text, encoding="utf8")
    (target / OUTPUT_PROJECTION).write_text(
        json.dumps(report.get("client_safe_projection") or {}, indent=2, sort_keys=True) + "\n", encoding="utf8"
    )


def _dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def _job_record(
    *,
    job_id: str,
    status: str,
    overall_status: str | None = None,
    evidence_class: str | None = None,
    blockers: list[str] | tuple[str, ...] = (),
    artifacts_written: bool = False,
) -> dict[str, Any]:
    return {
        "artifacts_written": artifacts_written,
        "blockers": list(blockers),
        "evidence_class": evidence_class,
        "id": job_id,
        "overall_status": overall_status,
        "status": status,
    }


def _classify_job_exception(exc: BaseException) -> tuple[str, str]:
    message = str(exc).lower()
    if "does not exist" in message:
        return "unavailable", "input_unavailable"
    if "secret-like" in message or "raw payload" in message:
        return "blocked", "secret_like_or_unsafe_input"
    if "traversal" in message:
        return "blocked", "path_traversal_blocked"
    if "malformed" in message or "must be a json object" in message:
        return "malformed", "input_malformed"
    if "only local json" in message:
        return "blocked", "path_traversal_blocked"
    if isinstance(exc, json.JSONDecodeError):
        return "malformed", "input_malformed"
    if isinstance(exc, OSError):
        return "failed", "input_failed"
    return "failed", "job_failed"


def _load_manifest(path: str) -> list[Any]:
    if _path_is_unsafe(path):
        raise ValueError("only local JSON report paths without traversal are supported")
    target = Path(path)
    if not target.is_file():
        raise ValueError(f"manifest does not exist: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf8"))
    except json.JSONDecodeError as exc:
        raise ValueError("malformed JSON in manifest") from exc
    if not isinstance(value, dict):
        raise ValueError("manifest must be a JSON object")
    reject_unsafe_input(value, label="manifest")
    jobs = value.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("manifest must be a JSON object with a jobs array")
    if len(jobs) > MAX_BATCH_JOBS:
        raise ValueError(f"batch job count exceeds maximum of {MAX_BATCH_JOBS}")
    seen: set[str] = set()
    duplicates = False
    for raw in jobs:
        if not isinstance(raw, dict):
            continue
        job_id = raw.get("id")
        if not isinstance(job_id, str) or not job_id:
            continue
        if job_id in seen:
            duplicates = True
            break
        seen.add(job_id)
    if duplicates:
        raise ValueError("duplicate batch job ids are not accepted")
    return jobs


def _job_display_id(raw: Any, index: int) -> str:
    if isinstance(raw, dict) and isinstance(raw.get("id"), str) and _job_id_is_safe(raw["id"]):
        return raw["id"]
    return f"job-{index}"


def _run_one_job(
    raw: Any,
    *,
    index: int,
    output_root: str | None,
    live_requested: bool,
) -> dict[str, Any]:
    display_id = _job_display_id(raw, index)
    if not isinstance(raw, dict):
        return _job_record(
            job_id=display_id,
            status="malformed",
            overall_status="malformed",
            evidence_class="malformed",
            blockers=("job_malformed",),
        )
    job_id = raw.get("id")
    if not isinstance(job_id, str) or not _job_id_is_safe(job_id):
        return _job_record(
            job_id=display_id,
            status="malformed",
            overall_status="malformed",
            evidence_class="malformed",
            blockers=("job_id_invalid",),
        )
    pillars: dict[str, dict[str, Any] | None] = {}
    for key in JOB_PATH_KEYS:
        value = raw.get(key)
        if value is None or value == "":
            pillars[key] = None
            continue
        if not isinstance(value, str):
            return _job_record(
                job_id=job_id,
                status="malformed",
                overall_status="malformed",
                evidence_class="malformed",
                blockers=(f"{key}_malformed",),
            )
        try:
            pillars[key] = _read(value, label=JOB_PATH_LABELS[key])
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            status, blocker = _classify_job_exception(exc)
            return _job_record(
                job_id=job_id,
                status=status,
                overall_status=status,
                evidence_class=status,
                blockers=(blocker,),
            )
    try:
        cycle = build_commerce_operations_cycle(
            pillars["marketplace_trend_report"],
            pillars["supplier_feasibility_report"],
            pillars["consumer_attention_report"],
            live_requested=live_requested,
        )
        report = cycle.to_dict()
        artifacts_written = False
        if output_root:
            report["artifacts_written"] = True
            report["safety_summary"] = dict(report["safety_summary"])
            report["safety_summary"]["artifacts_written"] = True
            _write_output(str(Path(output_root) / job_id), report, cycle.to_markdown())
            artifacts_written = True
        return _job_record(
            job_id=job_id,
            status="admitted",
            overall_status=str(report.get("overall_status")),
            evidence_class=str(report.get("evidence_class")),
            blockers=tuple(report.get("blockers") or ()),
            artifacts_written=artifacts_written,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        status, blocker = _classify_job_exception(exc)
        return _job_record(
            job_id=job_id,
            status=status,
            overall_status=status,
            evidence_class=status,
            blockers=(blocker,),
        )


def _batch_summary(*, live_requested: bool, jobs: list[dict[str, Any]]) -> dict[str, Any]:
    admitted = sum(1 for job in jobs if job["status"] == "admitted")
    return {
        "admitted_count": admitted,
        "failed_count": len(jobs) - admitted,
        "generated_at": GENERATED_AT,
        "job_count": len(jobs),
        "jobs": jobs,
        "live_requested": live_requested,
        "report_version": BATCH_REPORT_VERSION,
    }


def _batch_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Commerce Operations Cycle Batch",
        "",
        f"Generated at: `{summary['generated_at']}`",
        f"Jobs: {summary['job_count']} admitted {summary['admitted_count']}, not admitted {summary['failed_count']}",
        f"Live requested: `{summary['live_requested']}` (fail-closed; live commerce operations are not implemented)",
        "",
        "| Job | Status | Overall | Evidence class | Blockers |",
        "| --- | --- | --- | --- | --- |",
    ]
    for job in summary["jobs"]:
        blockers = ", ".join(job.get("blockers") or []) or "none"
        lines.append(
            f"| {job['id']} | `{job['status']}` | `{job.get('overall_status') or 'none'}` | `{job.get('evidence_class') or 'none'}` | {blockers} |"
        )
    lines += [
        "",
        "This is bounded CLI I/O over the existing cycle. It does not add a second scorer, packet type, or provider path.",
        "",
    ]
    return "\n".join(lines)


def _run_manifest_batch(
    *,
    manifest_path: str,
    output: str | None,
    markdown: bool,
    live_requested: bool,
) -> int:
    if output and _output_is_unsafe(output):
        raise ValueError("output traversal is not allowed")
    raw_jobs = _load_manifest(manifest_path)
    records = [
        _run_one_job(raw, index=index, output_root=output, live_requested=live_requested)
        for index, raw in enumerate(raw_jobs, start=1)
    ]
    summary = _batch_summary(live_requested=live_requested, jobs=records)
    rendered = _batch_markdown(summary) if markdown else _dumps(summary)
    if output:
        target = Path(output)
        target.mkdir(parents=True, exist_ok=True)
        (target / BATCH_SUMMARY_NAME).write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf8"
        )
    print(rendered)
    return 0 if summary["failed_count"] == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline MarketOS commerce-operations readiness cycle")
    parser.add_argument("--marketplace-trend-report")
    parser.add_argument("--supplier-feasibility-report")
    parser.add_argument("--consumer-attention-report")
    parser.add_argument(
        "--manifest",
        help="Local JSON object with a jobs array of existing pillar triples. Mutually exclusive with the three report flags. Max 8 jobs.",
    )
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--live", action="store_true", help="Rejected: live mode is not implemented and fail-closes as blocked")
    args = parser.parse_args(argv)
    if args.json and args.markdown:
        parser.error("choose --json or --markdown")
    report_flags = (
        args.marketplace_trend_report,
        args.supplier_feasibility_report,
        args.consumer_attention_report,
    )
    if args.manifest and any(report_flags):
        parser.error("--manifest cannot be combined with the three report flags")
    try:
        if args.manifest:
            return _run_manifest_batch(
                manifest_path=args.manifest,
                output=args.output,
                markdown=args.markdown,
                live_requested=args.live,
            )
        if any(report_flags):
            market = _read(args.marketplace_trend_report, label="marketplace report")
            supplier = _read(args.supplier_feasibility_report, label="supplier report")
            consumer = _read(args.consumer_attention_report, label="consumer report")
        else:
            market, supplier, consumer = _default_reports()
            reject_unsafe_input(market, label="marketplace report")
            reject_unsafe_input(supplier, label="supplier report")
            reject_unsafe_input(consumer, label="consumer report")
        cycle = build_commerce_operations_cycle(market, supplier, consumer, live_requested=args.live)
        report = cycle.to_dict()
        if args.output:
            report["artifacts_written"] = True
            report["safety_summary"] = dict(report["safety_summary"])
            report["safety_summary"]["artifacts_written"] = True
            _write_output(args.output, report, cycle.to_markdown())
        print(cycle.to_markdown() if args.markdown else json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"commerce_operations_cycle_error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
