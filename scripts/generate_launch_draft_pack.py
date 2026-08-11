"""Generate an offline, human-reviewable Launch Draft Pack."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.commerce.launch_draft_pack import build_launch_draft_pack, markdown  # noqa: E402
from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis  # noqa: E402
from scripts.run_product_opportunity_synthesis import _default_reports  # noqa: E402


def _read(value: str | None, *, label: str) -> dict[str, Any] | None:
    if not value:
        return None
    normalized = value.replace("\\", "/")
    target = Path(value)
    if ".." in target.parts or ".." in normalized.split("/") or target.suffix.lower() != ".json":
        raise ValueError(f"{label} path traversal or non-JSON input is not allowed")
    if not target.is_file():
        raise ValueError(f"{label} does not exist: {target}")
    parsed = json.loads(target.read_text(encoding="utf8"))
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must contain a JSON object")
    raw = json.dumps(parsed, sort_keys=True).lower()
    if any(token in raw for token in ("cj_api_key", "authorization", "access_token", "secret_key", "password")):
        raise ValueError(f"{label} contains secret-like content")
    return parsed


def _write(target: str, pack: dict[str, Any], md: str) -> None:
    directory = Path(target)
    if ".." in directory.parts or ".." in target.replace("\\", "/").split("/"):
        raise ValueError("output path traversal is not allowed")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "launch_draft_pack.json").write_text(json.dumps(pack, indent=2, sort_keys=True) + "\n", encoding="utf8")
    (directory / "launch_draft_pack.md").write_text(md, encoding="utf8")
    (directory / "shopify_draft_payload.json").write_text(json.dumps(pack["shopify_draft_payload"], indent=2, sort_keys=True) + "\n", encoding="utf8")
    (directory / "medusa_draft_payload.json").write_text(json.dumps(pack["medusa_draft_payload"], indent=2, sort_keys=True) + "\n", encoding="utf8")
    (directory / "creative_test_matrix.json").write_text(json.dumps(pack["creative_test_matrix"], indent=2, sort_keys=True) + "\n", encoding="utf8")
    ugc = "# UGC Briefs\n\n" + "\n\n".join(f"## {item['brief_type']}\n\n{item['creator_brief']}\n\nOpening hook: {item['opening_hook']}\n\nShot list:\n" + "\n".join(f"- {shot}" for shot in item["shot_list"]) for item in pack["ugc_briefs"]) + "\n"
    (directory / "ugc_briefs.md").write_text(ugc, encoding="utf8")
    checklist = pack["approval_checklist"]
    (directory / "approval_checklist.md").write_text("# Approval Checklist\n\n" + "\n".join(f"- [ ] {item}" for item in checklist["items"]) + "\n\n## Blockers\n\n" + "\n".join(f"- {item}" for item in checklist["blockers"]) + "\n", encoding="utf8")
    (directory / "operator_risk_review.json").write_text(json.dumps(pack["risk_review"], indent=2, sort_keys=True) + "\n", encoding="utf8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a deterministic, draft-only Launch Draft Pack")
    parser.add_argument("--opportunity-synthesis-report")
    parser.add_argument("--product-validation-report")
    parser.add_argument("--consumer-attention-report")
    parser.add_argument("--supplier-feasibility-report")
    parser.add_argument("--marketplace-trend-report")
    parser.add_argument("--client-context")
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    if args.json and args.markdown:
        parser.error("choose --json or --markdown")
    try:
        synthesis = _read(args.opportunity_synthesis_report, label="opportunity synthesis report")
        product_validation = _read(args.product_validation_report, label="product validation report")
        consumer = _read(args.consumer_attention_report, label="consumer attention report")
        supplier = _read(args.supplier_feasibility_report, label="supplier feasibility report")
        market = _read(args.marketplace_trend_report, label="marketplace trend report")
        context = _read(args.client_context, label="client context")
        if synthesis is None:
            market, supplier, consumer = _default_reports()
            synthesis = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
        pack = build_launch_draft_pack(synthesis=synthesis, product_validation=product_validation, consumer_attention=consumer, supplier_feasibility=supplier, marketplace_trend=market, client_context=context).to_dict()
        md = markdown(pack)
        if args.output:
            _write(args.output, pack, md)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(md if args.markdown else json.dumps(pack, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
