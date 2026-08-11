"""Generate an offline platform-agnostic site/store/funnel blueprint."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.commerce.launch_draft_pack import build_launch_draft_pack  # noqa: E402
from evaluation.commerce.site_draft_builder import build_site_draft_pack, markdown  # noqa: E402
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


def _write(directory_name: str, pack: dict[str, Any], md: str) -> None:
    directory = Path(directory_name)
    normalized = directory_name.replace("\\", "/")
    if ".." in directory.parts or ".." in normalized.split("/"):
        raise ValueError("output path traversal is not allowed")
    directory.mkdir(parents=True, exist_ok=True)
    files = {
        "site_draft_pack.json": pack,
        "route_manifest.json": pack["route_manifest"],
        "section_library.json": pack["section_library"],
        "cms_content_model.json": pack["cms_content_model"],
        "static_site_payload.json": pack["platform_payloads"]["static_site"],
        "shopify_theme_draft_payload.json": pack["platform_payloads"]["shopify_theme"],
        "medusa_storefront_draft_payload.json": pack["platform_payloads"]["medusa_storefront"],
        "woocommerce_draft_payload.json": pack["platform_payloads"]["woocommerce"],
        "webflow_cms_draft_payload.json": pack["platform_payloads"]["webflow_cms"],
        "wix_headless_draft_payload.json": pack["platform_payloads"]["wix_headless"],
        "squarespace_draft_payload.json": pack["platform_payloads"]["squarespace"],
        "carrd_microsite_payload.json": pack["platform_payloads"]["carrd_microsite"],
        "operator_risk_review.json": pack["risk_review"],
    }
    for filename, value in files.items():
        (directory / filename).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf8")
    (directory / "site_draft_pack.md").write_text(md, encoding="utf8")
    (directory / "seo_plan.md").write_text("# SEO Plan\n\n" + json.dumps(pack["seo_plan"], indent=2, sort_keys=True) + "\n", encoding="utf8")
    (directory / "analytics_plan.md").write_text("# Analytics Plan\n\n" + json.dumps(pack["analytics_plan"], indent=2, sort_keys=True) + "\n", encoding="utf8")
    (directory / "conversion_test_plan.md").write_text("# Conversion Test Plan\n\n" + "\n".join(f"- {item.get('test_id')}: {item.get('hypothesis')} Target: {item.get('target_metric')}." for item in pack["conversion_test_plan"]["tests"]) + "\n", encoding="utf8")
    (directory / "deployment_readiness_checklist.md").write_text("# Deployment Readiness\n\n" + "\n".join(f"- {key}: {value.get('status')} — {value.get('detail')}" for key, value in pack["deployment_readiness"]["checks"].items()) + "\n", encoding="utf8")
    (directory / "approval_checklist.md").write_text("# Approval Checklist\n\n" + "\n".join(f"- [ ] {item}" for item in pack["approval_checklist"]["items"]) + "\n\n## Blockers\n\n" + "\n".join(f"- {item}" for item in pack["approval_checklist"]["blockers"]) + "\n", encoding="utf8")


def _defaults() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    market, supplier, consumer = _default_reports()
    synthesis = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    launch = build_launch_draft_pack(synthesis=synthesis, marketplace_trend=market, supplier_feasibility=supplier, consumer_attention=consumer).to_dict()
    return launch, synthesis, market, supplier, consumer


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Generate a deterministic platform-agnostic site draft pack")
    parser.add_argument("--launch-draft-pack")
    parser.add_argument("--opportunity-synthesis-report")
    parser.add_argument("--product-validation-report")
    parser.add_argument("--marketplace-trend-report")
    parser.add_argument("--supplier-feasibility-report")
    parser.add_argument("--consumer-attention-report")
    parser.add_argument("--client-context")
    parser.add_argument("--site-type")
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    if args.json and args.markdown:
        parser.error("choose --json or --markdown")
    try:
        launch = _read(args.launch_draft_pack, label="launch draft pack")
        synthesis = _read(args.opportunity_synthesis_report, label="opportunity synthesis report")
        validation = _read(args.product_validation_report, label="product validation report")
        market = _read(args.marketplace_trend_report, label="marketplace trend report")
        supplier = _read(args.supplier_feasibility_report, label="supplier feasibility report")
        consumer = _read(args.consumer_attention_report, label="consumer attention report")
        context = _read(args.client_context, label="client context")
        if launch is None and synthesis is None and context is None:
            launch, synthesis, market, supplier, consumer = _defaults()
        elif synthesis is None and launch is not None:
            synthesis = {"top_candidate_id": launch.get("candidate_id"), "top_candidate_title": launch.get("candidate_title"), "evidence_mode": launch.get("evidence_mode", "fixture_demo"), "overall_recommendation": launch.get("overall_recommendation", "hold_for_manual_review"), "candidates": [{"candidate_id": launch.get("candidate_id"), "title": launch.get("candidate_title"), "top_hooks": launch.get("ad_creatives", {}).get("hooks", [])}]}
        pack = build_site_draft_pack(launch_draft_pack=launch, opportunity_synthesis=synthesis, product_validation=validation, marketplace_trends=market, supplier_feasibility=supplier, consumer_attention=consumer, client_context=context, site_type=args.site_type).to_dict()
        md = markdown(pack)
        if args.output:
            _write(args.output, pack, md)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(md if args.markdown else json.dumps(pack, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
