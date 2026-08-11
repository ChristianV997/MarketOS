"""Report Phase 1 gates before an agent starts a new MarketOS feature."""
from __future__ import annotations

import argparse
from typing import Any

try:
    from .operating_layer import changed_from_git, normal_paths, render_json_or_markdown, write_optional_output
except ImportError:  # pragma: no cover - direct script execution
    from operating_layer import changed_from_git, normal_paths, render_json_or_markdown, write_optional_output


GATES = {
    "supplier_mutation": "No supplier mutation before live read-only CJ proof.",
    "shopify_mutation": "No Shopify mutation before an approval ledger exists.",
    "ads": "No ads before a spend cap and kill switch exist.",
    "new_supplier_provider": "No supplier provider before the CJ read-only validation result is recorded.",
    "broad_phase2": "No broad Phase 2 feature before the Phase 1 live readiness report.",
    "generated_artifacts": "Generated artifacts must not be committed to a PR.",
    "credentials": "Credentials and .env files must not be committed.",
}
TERM_GATES = {
    "supplier_mutation": ("supplier mutation", "create order", "place order", "inventory write"),
    "shopify_mutation": ("shopify product create", "shopify mutation", "publish product"),
    "ads": ("launch ad", "ad spend", "create campaign"),
    "new_supplier_provider": ("zendrop adapter", "new supplier provider"),
}


def check(paths: list[str], text: str = "", candidate: str | None = None) -> dict[str, Any]:
    paths = normal_paths(paths); lowered = text.lower()
    blockers: list[str] = []
    if candidate in GATES: blockers.append(candidate)
    for gate, terms in TERM_GATES.items():
        if any(term in lowered for term in terms): blockers.append(gate)
    if any(path.startswith("artifacts/") or path.endswith((".jsonl", ".har")) for path in paths): blockers.append("generated_artifacts")
    if any(".env" in path.lower() and not path.endswith(".example") for path in paths): blockers.append("credentials")
    return {"phase": "phase1", "changed_files": paths, "candidate": candidate, "status": "blocked" if blockers else "clear", "blockers": sorted(set(blockers)), "gate_definitions": GATES, "next_action": "resolve the listed gate before implementation" if blockers else "task is not blocked by encoded phase gates"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", action="append", default=[]); parser.add_argument("--from-git", action="store_true")
    parser.add_argument("--text", default=""); parser.add_argument("--candidate", choices=tuple(GATES)); parser.add_argument("--json", action="store_true"); parser.add_argument("--markdown", action="store_true"); parser.add_argument("--output")
    args = parser.parse_args(argv)
    if args.json and args.markdown: parser.error("choose --json or --markdown")
    report = check(list(args.path) + (changed_from_git() if args.from_git else []), args.text, args.candidate)
    content = render_json_or_markdown(report, markdown=args.markdown, title="MarketOS phase gate")
    write_optional_output(content, args.output); print(content, end="")
    return 0


if __name__ == "__main__": raise SystemExit(main())
