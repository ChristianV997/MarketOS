"""Run bounded end-of-session checks and generate the shared handoff."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(command: list[str], root: Path) -> int:
    return subprocess.run(command, cwd=root, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--tests", nargs="+", default=["tests/test_ai_dev_stack.py", "tests/test_ollama_benchmark.py"])
    parser.add_argument("--dry-run", action="store_true", help="run checks without writing the handoff")
    args = parser.parse_args()
    root = args.repository.resolve()
    if run([sys.executable, "-m", "pytest", *args.tests, "-q"], root) != 0:
        return 1
    if run(["git", "diff", "--check"], root) != 0:
        return 1
    if args.dry_run:
        print("Checks passed; handoff not written (--dry-run).")
        return 0
    output = root / "docs" / "ai" / "SESSION_HANDOFF.md"
    return run([sys.executable, "scripts/ai/generate_session_handoff.py", "--repository", str(root), "--output", str(output)], root)


if __name__ == "__main__":
    raise SystemExit(main())
