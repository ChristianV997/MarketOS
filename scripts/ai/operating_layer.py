"""Shared deterministic helpers for the local Agentic Engineering tools."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]


def git_lines(*args: str, root: Path = ROOT) -> list[str]:
    result = subprocess.run(["git", "-C", str(root), *args], text=True, capture_output=True, check=False)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def changed_from_git(root: Path = ROOT) -> list[str]:
    """Include tracked and untracked paths without reading their contents."""
    paths = set(git_lines("diff", "--name-only", "HEAD", root=root))
    result = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], text=True, capture_output=True, check=False)
    for line in result.stdout.splitlines():
        if len(line) >= 4:
            path = line[3:].split(" -> ")[-1].replace("\\", "/")
            paths.add(path)
    return sorted(paths)


def staged_from_git(root: Path = ROOT) -> list[str]:
    """Return only the intentional index, excluding unrelated worktree files."""
    return normal_paths(git_lines("diff", "--cached", "--name-only", root=root))


def normal_paths(paths: Iterable[str]) -> list[str]:
    normalized = []
    for path in paths:
        value = str(path).replace("\\", "/")
        normalized.append(value[2:] if value.startswith("./") else value)
    return sorted({path for path in normalized if path.strip()})


def docs_only(paths: Iterable[str]) -> bool:
    items = normal_paths(paths)
    return bool(items) and all(path.startswith(("docs/", ".github/")) or path in {"README.md", "AGENTS.md", "CLAUDE.md"} for path in items)


def render_json_or_markdown(report: dict[str, Any], *, markdown: bool, title: str) -> str:
    if not markdown:
        return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)
    lines = [f"# {title}", ""]
    for key, value in report.items():
        if isinstance(value, (list, tuple)):
            lines.append(f"## {key.replace('_', ' ').title()}")
            lines.extend(f"- `{item}`" if not isinstance(item, dict) else f"- `{json.dumps(item, sort_keys=True)}`" for item in value)
            lines.append("")
        elif isinstance(value, dict):
            lines.append(f"## {key.replace('_', ' ').title()}")
            lines.extend(f"- `{name}`: `{item}`" for name, item in value.items())
            lines.append("")
        else:
            lines.append(f"- **{key.replace('_', ' ')}**: `{value}`")
    return "\n".join(lines).rstrip() + "\n"


def write_optional_output(content: str, output: str | None) -> None:
    if output:
        Path(output).write_text(content + ("" if content.endswith("\n") else "\n"), encoding="utf-8")
