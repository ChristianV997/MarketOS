"""Generate the offline CompanyOS architecture and agent registry report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.companyos.companyos_registry_report import build_companyos_registry_report

SECRET_KEYS = {"password", "secret", "token", "api_key", "apikey", "private_key", "access_token", "refresh_token", "client_secret"}


def _path(value: str | None) -> Path | None:
    if not value:
        return None
    raw = Path(value)
    if any(part == ".." for part in raw.parts):
        raise ValueError("path traversal is not accepted")
    path = raw if raw.is_absolute() else ROOT / raw
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path


def _secret_like(value: Any) -> bool:
    if isinstance(value, dict):
        return any(str(key).lower().replace("-", "_") in SECRET_KEYS or _secret_like(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_secret_like(item) for item in value)
    return False


def _seed(path_value: str | None) -> dict[str, Any] | None:
    path = _path(path_value)
    if not path:
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    if _secret_like(value):
        raise ValueError(f"secret-like fields are not accepted in {path.name}")
    return value


def _exports(output_value: str, report: Any) -> None:
    output = Path(output_value)
    if any(part == ".." for part in output.parts):
        raise ValueError("output traversal is not accepted")
    if not output.is_absolute():
        output = ROOT / output
    output.mkdir(parents=True, exist_ok=True)
    data = report.to_dict()
    files = {
        "companyos_registry_report.json": json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "companyos_registry_report.md": report.to_markdown(),
        "architecture_registry.json": json.dumps(data["architecture"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "integration_roadmap.md": "## Integration Roadmap\n\n" + "\n".join(f"- {item['system_id']}: {item['decision']} ({item['priority']})" for item in data["integration_decisions"]) + "\n",
        "agent_registry.json": json.dumps(data["agents"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "skill_registry.json": json.dumps(data["skills"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "tool_registry.json": json.dumps(data["tools"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "workflow_registry.json": json.dumps(data["workflows"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "model_routing_policy.json": json.dumps(data["model_router"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "eval_policy.json": json.dumps(data["eval_registry"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "knowledge_registry.json": json.dumps(data["knowledge"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    }
    for name, content in files.items():
        (output / name).write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--architecture-seed")
    parser.add_argument("--agent-seed")
    parser.add_argument("--skill-seed")
    parser.add_argument("--tool-seed")
    parser.add_argument("--workflow-seed")
    parser.add_argument("--model-router-seed")
    parser.add_argument("--eval-seed")
    parser.add_argument("--knowledge-seed")
    parser.add_argument("--include-architecture", action="store_true")
    parser.add_argument("--include-agents", action="store_true")
    parser.add_argument("--include-skills", action="store_true")
    parser.add_argument("--include-tools", action="store_true")
    parser.add_argument("--include-workflows", action="store_true")
    parser.add_argument("--include-model-router", action="store_true")
    parser.add_argument("--include-evals", action="store_true")
    parser.add_argument("--include-knowledge", action="store_true")
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    if args.json and args.markdown:
        parser.error("choose --json or --markdown")
    try:
        seeds = {}
        for key, value in (("architecture", args.architecture_seed), ("agents", args.agent_seed), ("skills", args.skill_seed), ("tools", args.tool_seed), ("workflows", args.workflow_seed), ("model_router", args.model_router_seed), ("evals", args.eval_seed), ("knowledge", args.knowledge_seed)):
            loaded = _seed(value)
            if loaded is not None:
                seeds[key] = loaded
        report = build_companyos_registry_report(seeds=seeds)
        if args.output:
            _exports(args.output, report)
        print(report.to_markdown() if args.markdown else json.dumps(report.to_dict(), indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"companyos_registry_error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
