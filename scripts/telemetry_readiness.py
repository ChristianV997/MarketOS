"""Read-only Sentry/PostHog telemetry readiness report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.observability.phase1_telemetry import telemetry_readiness
from backend.observability.telemetry_sanitization import sanitize_sentry_event, telemetry_contains_forbidden_data


def _values(path: str | None) -> dict[str, str]:
    import os

    values = dict(os.environ)
    if path:
        for line in (ROOT / path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                name, value = line.split("=", 1)
                values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def build_report(environ: dict[str, str] | None = None, *, test_sanitization: bool = False) -> dict[str, object]:
    report = telemetry_readiness(environ)
    report["optional"] = True
    report["fail_open"] = True
    report["credentials_printed"] = False
    report["network_calls"] = False
    report["mutated"] = False
    report["missing_optional"] = []
    values = environ or {}
    if not values.get("SENTRY_DSN"):
        report["missing_optional"].append("SENTRY_DSN")
    if not values.get("VITE_POSTHOG_KEY"):
        report["missing_optional"].append("VITE_POSTHOG_KEY")
    report["sanitization_test"] = {"run": False}
    if test_sanitization:
        sample = {"request": {"data": {"email": "person@example.test"}, "headers": {"authorization": "Bearer " + "a" * 32}}, "user": {"email": "person@example.test"}}
        sanitized = sanitize_sentry_event(sample)
        report["sanitization_test"] = {"run": True, "forbidden_data_remaining": telemetry_contains_forbidden_data(sanitized), "request_body_removed": "data" not in sanitized.get("request", {})}
    report["next_actions"] = ["Set server-only SENTRY_DSN after reviewing privacy and sampling.", "Set VITE_POSTHOG_KEY only if explicit browser analytics are approved.", "Keep telemetry optional; absence must not block the MVP."]
    return report


def markdown_report(report: dict[str, object]) -> str:
    lines = ["# MarketOS telemetry readiness", "", f"- Sentry configured: **{report['sentry_configured']}**", f"- Sentry enabled: **{report['sentry_enabled']}**", f"- PostHog frontend configured: **{report['posthog_frontend_configured']}**", f"- Safe mode: **{report['safe_mode']}**", f"- PII disabled: **{report['sentry_pii_disabled']}**", f"- Fail open: **{report['telemetry_fail_open']}**", "", "## Next actions", ""]
    lines.extend(f"- {item}" for item in report["next_actions"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file")
    parser.add_argument("--output")
    parser.add_argument("--test-sanitization", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true")
    mode.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    report = build_report(_values(args.env_file), test_sanitization=args.test_sanitization)
    rendered = markdown_report(report) if args.markdown else json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.output:
        target = (ROOT / args.output).resolve()
        artifacts = (ROOT / "artifacts").resolve()
        if target != artifacts and artifacts not in target.parents:
            parser.error("--output must stay under artifacts/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
