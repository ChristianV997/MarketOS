"""Reduce test logs to actionable failures and summary lines."""
from __future__ import annotations

import argparse
import re
from pathlib import Path


PATTERNS = (
    re.compile(r"FAILED|ERROR|FAILURES|=+ .* (passed|failed|skipped)", re.IGNORECASE),
    re.compile(r"^\s*E\s"),
    re.compile(r"^short test summary info", re.IGNORECASE),
    re.compile(r"^\s*[^\s].*::.*(FAILED|ERROR|XFAIL|XPASS)", re.IGNORECASE),
    re.compile(r"^\s*(collected|warnings summary)", re.IGNORECASE),
)


def filter_lines(text: str) -> str:
    lines = text.splitlines()
    keep = [line for line in lines if any(pattern.search(line) for pattern in PATTERNS)]
    return "\n".join(keep) + ("\n" if keep else "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    print(filter_lines(args.input.read_text(encoding="utf-8", errors="replace")), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
