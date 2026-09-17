"""Recommend fast, additive test commands from changed MarketOS paths."""
from __future__ import annotations

import argparse
from typing import Any

try:  # Supports both ``python scripts/ai/...`` and package-style tests.
    from .operating_layer import changed_from_git, docs_only, normal_paths, render_json_or_markdown, write_optional_output
except ImportError:  # pragma: no cover - direct script execution
    from operating_layer import changed_from_git, docs_only, normal_paths, render_json_or_markdown, write_optional_output


RULES = (
    (("backend/adapters/research/cj_", "backend/mvp_commerce/supplier_evidence"), ("pytest tests/test_cj_readonly_supplier.py -q", "pytest tests/integration/test_supplier_readonly_preflight.py -q", "pytest tests/test_phase1_live_validation_harness.py -q", "pytest tests/evaluation -q"), "supplier_evidence"),
    (("evaluation/commerce/",), ("pytest tests/evaluation -q", "pytest tests/contracts/test_architecture_boundaries.py -q"), "evaluation"),
    (("api/routes/", "backend/events/"), ("pytest tests/integration/test_canonical_events_api_readonly.py -q", "pytest tests/system/test_canonical_event_read_views.py -q"), "api_events"),
    (("frontend/",), ("cd frontend && npm run build",), "frontend"),
    (("scripts/ai/",), ("pytest tests/test_ai_dev_stack.py -q", "pytest tests/ai/test_operator_context_snapshot.py -q", "python scripts/ai/session_finish.py --dry-run"), "agentic_tools"),
    ((".github/workflows/",), ("python -m compileall -q scripts tests", "python scripts/ai/ci_matrix_plan.py --json"), "ci_workflow"),
)


def select(paths: list[str]) -> dict[str, Any]:
    paths = normal_paths(paths)
    commands: list[str] = []
    lanes: list[str] = []
    if docs_only(paths):
        commands = ["git diff --check", "python scripts/ai/session_finish.py --dry-run"]
        lanes = ["docs_only"]
    else:
        for prefixes, rule_commands, lane in RULES:
            if any(path.startswith(prefixes) for path in paths):
                commands.extend(rule_commands); lanes.append(lane)
        if not commands:
            commands = ["python -m compileall -q backend api scripts tests", "pytest tests/contracts/test_architecture_boundaries.py -q"]
            lanes = ["unknown_fallback"]
        commands.extend(["git diff --check", "python scripts/ai/session_finish.py --dry-run"])
    return {"changed_files": paths, "lanes": sorted(set(lanes)), "recommended_commands": list(dict.fromkeys(commands)), "docs_only": docs_only(paths)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--from-git", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    if args.json and args.markdown: parser.error("choose --json or --markdown")
    paths = list(args.path) + (changed_from_git() if args.from_git else [])
    report = select(paths)
    content = render_json_or_markdown(report, markdown=args.markdown, title="MarketOS focused test selection")
    write_optional_output(content, args.output); print(content, end="")
    return 0


if __name__ == "__main__": raise SystemExit(main())
