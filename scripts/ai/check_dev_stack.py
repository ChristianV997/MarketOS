"""Read-only capability probe for a portable AI development environment."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


TOOLS = ("python", "node", "npm", "npx", "uv", "docker", "git", "ollama", "semgrep", "codeql", "repomix", "serena", "graphify")
KNOWN_REPOS = ("MarketOS", "NeuroTopology-Sim", "AI-DevStack")


def version(command: str) -> str | None:
    path = shutil.which(command)
    if not path and command == "semgrep":
        user_script = Path(os.environ.get("APPDATA", "")) / "Python" / f"Python{sys.version_info.major}{sys.version_info.minor}" / "Scripts" / "semgrep.exe"
        if user_script.exists():
            path = str(user_script)
    if not path and command == "repomix":
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidate = Path(appdata) / "npm" / "repomix.ps1"
            if candidate.exists():
                path = str(candidate)
    if not path:
        return None
    try:
        env = os.environ.copy()
        env["PATH"] = str(Path(path).parent) + os.pathsep + env.get("PATH", "")
        probe_timeout = 15 if command in {"semgrep", "repomix"} else 5
        result = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=probe_timeout, check=False, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return "available (version probe failed)"
    text = (result.stdout or result.stderr).strip().splitlines()
    return text[0] if text else "available"


def find_repo(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _obsidian_config_exists() -> bool:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return False
    return (Path(appdata) / "obsidian" / "obsidian.json").exists()


def _ollama_has_models() -> bool:
    if not shutil.which("ollama"):
        return False
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return any(line.strip() and not line.startswith("NAME") for line in result.stdout.splitlines())


def _workspace_overview(start: Path) -> dict[str, dict[str, str | bool | None]]:
    roots: dict[str, dict[str, str | bool | None]] = {}
    for name in KNOWN_REPOS:
        candidate = start.parent / name
        if candidate.exists():
            roots[name] = {
                "path": str(candidate.resolve()),
                "git": (candidate / ".git").exists(),
                "docs_ai": (candidate / "docs" / "ai").exists(),
                "scripts_ai": (candidate / "scripts" / "ai").exists(),
            }
    return roots


def probe(start: Path) -> dict:
    repo = find_repo(start)
    tools = {name: version(name) for name in TOOLS}
    if repo and (repo / ".serena" / "project.yml").exists():
        tools["serena"] = "configured via official uvx runner"
    return {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "cwd": str(start.resolve()),
        "repository": str(repo) if repo else None,
        "workspace": _workspace_overview(start),
        "tools": tools,
        "repository_files": {
            name: (repo / name).exists() if repo else False
            for name in ("AGENTS.md", "CLAUDE.md", ".claude", ".codex", "docs/ai", "scripts/ai", "semgrep/ai-safety.yml")
        },
        "optional_runtime": {
            "ollama_models": _ollama_has_models(),
            "obsidian_config": _obsidian_config_exists(),
        },
    }


def recommendations(report: dict) -> list[str]:
    """Return short, actionable next steps without recommending installations blindly."""
    actions: list[str] = []
    tools = report["tools"]
    if not tools.get("semgrep"):
        actions.append("Install or enable Semgrep before security-sensitive reviews")
    if not tools.get("git"):
        actions.append("Install Git for branch-aware handoffs")
    if tools.get("ollama") and not report["optional_runtime"]["ollama_models"]:
        actions.append("Ollama is available but has no model; benchmark one small local model before adopting it")
    if report["optional_runtime"]["obsidian_config"]:
        actions.append("Obsidian is detected; verify a loopback-only API before enabling a vault bridge")
    else:
        actions.append("Keep Obsidian integration deferred until a real vault and safe local API are confirmed")
    repo_files = report["repository_files"]
    if not repo_files.get("docs/ai") or not repo_files.get("scripts/ai"):
        actions.append("Complete the repo-local docs/ai and scripts/ai scaffold")
    return actions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=Path.cwd(), help="directory to inspect")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()
    report = probe(args.path)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Repository: {report['repository'] or 'not detected'}")
        if report["workspace"]:
            print("Workspace:")
            for name, info in report["workspace"].items():
                print(f"  {name}: {info['path']}")
        for name, value in report["tools"].items():
            print(f"{name}: {value or 'missing'}")
        print(f"Ollama models: {report['optional_runtime']['ollama_models']}")
        print(f"Obsidian config: {report['optional_runtime']['obsidian_config']}")
        print("Recommended next actions:")
        for action in recommendations(report):
            print(f"  - {action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
