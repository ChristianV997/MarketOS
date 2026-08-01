"""Generate a compact handoff template without reading source files."""
from __future__ import annotations

import argparse
import subprocess
from datetime import date
from pathlib import Path


def git_value(root: Path, args: list[str]) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    return result.stdout.strip() or "unknown"


def format_status(root: Path) -> str:
    result = subprocess.run(["git", "-C", str(root), "status", "--short"], capture_output=True, text=True, check=False)
    status = result.stdout.rstrip("\n")
    return status if status else "(clean or unavailable)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, help="write the handoff to a Markdown file")
    args = parser.parse_args()
    root = args.repository.resolve()
    content = (
        f"# Session Handoff\n"
        f"Date: {date.today().isoformat()}\n"
        f"Repository: {root}\n"
        f"Branch: {git_value(root, ['branch', '--show-current'])}\n"
        f"Objective:\n\n"
        f"## Files changed\n{format_status(root)}\n"
        f"## Interfaces affected\n\n"
        f"## Tests run\n\n"
        f"## Results\n\n"
        f"## Decisions made\n\n"
        f"## Risks\n\n"
        f"## Remaining blockers\n\n"
        f"## Next action\n\n"
        f"## What the next agent should inspect first\n"
    )
    if args.output:
        args.output.resolve().write_text(content, encoding="utf-8")
    else:
        print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
