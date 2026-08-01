"""Run the repository Semgrep policy with compact, agent-friendly output."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def semgrep_command() -> str | None:
    command = shutil.which("semgrep")
    if command:
        return command
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidate = Path(appdata) / "Python" / f"Python{sys.version_info.major}{sys.version_info.minor}" / "Scripts" / "semgrep.exe"
        if candidate.exists():
            return str(candidate)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--severity", choices=("INFO", "WARNING", "ERROR"), default=None)
    parser.add_argument("--json", action="store_true", help="emit filtered JSON")
    parser.add_argument("--fail-on-error", action="store_true", help="return non-zero when ERROR findings exist")
    args = parser.parse_args()

    command = semgrep_command()
    if not command:
        print("Semgrep is not installed or not available on PATH.", file=sys.stderr)
        return 2

    env = os.environ.copy()
    env["PATH"] = str(Path(command).parent) + os.pathsep + env.get("PATH", "")
    cmd = [command, "scan", "--quiet", "--config", "semgrep/ai-safety.yml", "--json", "."]
    if args.severity:
        cmd.extend(["--severity", args.severity])
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, check=False)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(result.stderr.strip() or result.stdout.strip(), file=sys.stderr)
        return 2

    findings = payload.get("results", [])
    if args.json:
        print(json.dumps({"errors": payload.get("errors", []), "results": findings}, indent=2))
    else:
        print(f"Semgrep findings: {len(findings)}")
        for finding in findings:
            extra = finding.get("extra", {})
            print(f"{finding.get('path')}:{finding.get('start', {}).get('line')} [{extra.get('severity')}] {finding.get('check_id')}")

    if payload.get("errors"):
        return 2
    if args.fail_on_error and any(f.get("extra", {}).get("severity") == "ERROR" for f in findings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
