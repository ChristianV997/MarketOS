"""Read-only preflight for the optional Phase 1 Crawl4AI worker profile.

This command never installs packages, downloads browser binaries, or fetches
pages. It is intentionally separate from the default API/runtime validation so
an operator can diagnose the opt-in JS-rendering profile before a live evidence
benchmark.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import sys
from typing import Any, Mapping


def _module_available(name: str, modules: Mapping[str, bool] | None) -> bool:
    if modules is not None:
        return bool(modules.get(name, False))
    return importlib.util.find_spec(name) is not None


def build_report(
    *,
    python_version: tuple[int, int, int] | None = None,
    modules: Mapping[str, bool] | None = None,
) -> dict[str, Any]:
    """Return a deterministic, no-network readiness assessment.

    Crawl4AI 0.8.6's reviewed optional profile currently pins the lxml 5.x
    line. The benchmark environment's CPython 3.14 had no matching wheel and
    failed a source build due to missing libxml2 headers. Treat that combination
    as a clear preflight blocker rather than retrying or silently changing the
    default dependency policy.
    """
    version = python_version or sys.version_info[:3]
    crawl4ai_available = _module_available("crawl4ai", modules)
    lxml_available = _module_available("lxml", modules)
    playwright_available = _module_available("playwright", modules)
    warnings: list[str] = []
    blockers: list[str] = []

    if version >= (3, 14, 0) and not crawl4ai_available:
        blockers.append("python_3_14_optional_profile_not_wheel_ready")
        warnings.append(
            "Crawl4AI 0.8.6 pins lxml 5.x; this profile may require a source build on CPython 3.14. "
            "Use an isolated CPython 3.12 or 3.13 operator runtime for the benchmark."
        )
    elif not crawl4ai_available:
        warnings.append("crawl4ai_not_installed")

    if crawl4ai_available and not lxml_available:
        blockers.append("crawl4ai_runtime_missing_lxml")
    if crawl4ai_available and not playwright_available:
        warnings.append("playwright_not_importable_browser_install_may_still_be_required")

    status = "ready_for_browser_probe" if not blockers and crawl4ai_available else "blocked" if blockers else "install_required"
    return {
        "status": status,
        "read_only": True,
        "network_calls": False,
        "python": {"version": ".".join(str(part) for part in version), "implementation": platform.python_implementation()},
        "optional_modules": {
            "crawl4ai": crawl4ai_available,
            "lxml": lxml_available,
            "playwright": playwright_available,
        },
        "warnings": warnings,
        "blockers": blockers,
        "next_action": (
            "Run the explicit JS benchmark with MARKETOS_PHASE1_JS_RENDER=1 and an exact CRAWL4AI_ALLOWED_DOMAINS allowlist."
            if status == "ready_for_browser_probe"
            else "Create an isolated CPython 3.12 or 3.13 environment, install requirements.txt and requirements-oss.txt there, then rerun this preflight."
            if blockers
            else "Install the reviewed optional profile with: python -m pip install -r requirements-oss.txt"
        ),
    }


def _markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Phase 1 Crawl4AI runtime preflight", "",
        f"- Status: `{report['status']}`",
        f"- Python: `{report['python']['implementation']} {report['python']['version']}`",
        f"- Crawl4AI importable: `{report['optional_modules']['crawl4ai']}`",
        f"- lxml importable: `{report['optional_modules']['lxml']}`",
        f"- Playwright importable: `{report['optional_modules']['playwright']}`", "",
        "## Blockers", "",
    ]
    lines.extend(f"- `{item}`" for item in report["blockers"])
    if not report["blockers"]:
        lines.append("- None")
    lines.extend(("", "## Next action", "", str(report["next_action"]), ""))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON (default)")
    parser.add_argument("--markdown", action="store_true", help="emit Markdown")
    args = parser.parse_args(argv)
    if args.json and args.markdown:
        parser.error("choose --json or --markdown")
    report = build_report()
    print(_markdown(report) if args.markdown else json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
