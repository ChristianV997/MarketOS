"""Print non-binding CI lanes recommended by the focused test selector."""
from __future__ import annotations

import argparse

try:
    from .operating_layer import changed_from_git, render_json_or_markdown, write_optional_output
    from .select_tests import select
except ImportError:  # pragma: no cover - direct script execution
    from operating_layer import changed_from_git, render_json_or_markdown, write_optional_output
    from select_tests import select


def plan(paths: list[str]) -> dict:
    selected = select(paths)
    lanes = ["python_compile", "architecture_boundaries", "security_semgrep"]
    lanes.extend(selected["lanes"])
    if selected["docs_only"]: lanes = ["docs_only", "diff_check"]
    return {"changed_files": selected["changed_files"], "recommended_lanes": list(dict.fromkeys(lanes)), "commands": selected["recommended_commands"], "note": "advisory only; this script does not alter GitHub Actions"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--path", action="append", default=[]); parser.add_argument("--from-git", action="store_true"); parser.add_argument("--json", action="store_true"); parser.add_argument("--markdown", action="store_true"); parser.add_argument("--output")
    args = parser.parse_args(argv)
    if args.json and args.markdown: parser.error("choose --json or --markdown")
    result = plan(list(args.path) + (changed_from_git() if args.from_git else []))
    content = render_json_or_markdown(result, markdown=args.markdown, title="MarketOS CI lane plan")
    write_optional_output(content, args.output); print(content, end=""); return 0


if __name__ == "__main__": raise SystemExit(main())
