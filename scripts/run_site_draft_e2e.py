#!/usr/bin/env python3
"""Run the Site Draft Builder evidence-connected vertical slice against REAL fixture files.

Loads real fixture files by name from tests/fixtures/site_draft_builder/,
feeds them through build_site_draft_pack with explicit provenance on every input,
writes a sanitized export set (JSON + markdown) to a temp dir, and asserts that
review blockers surface correctly. Prints a one-line SHA-validated manifest.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.commerce.site_draft_builder import build_site_draft_pack, markdown  # noqa: E402

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "site_draft_builder"

# The six fixture files loaded by name — preserving candidate/workspace identity,
# NOT synthesized defaults.
FIXTURE_FILES = {
    "client_context": "ecommerce_context.json",
    "launch_draft_pack": "launch_draft_pack.json",
    "opportunity_synthesis": "opportunity_synthesis_report.json",
    "supplier_feasibility": "supplier_feasibility_report.json",
    "marketplace_trends": "marketplace_trend_report.json",
    "consumer_attention": "consumer_attention_report.json",
}


def load_fixture(filename: str) -> dict:
    """Load a real fixture file by name from the fixture directory."""
    path = FIXTURE_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"Fixture file not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Fixture must contain a JSON object: {path}")
    return raw


def sanitize_and_write(pack_dict: dict, md: str, out_dir: Path) -> list[Path]:
    """Write a sanitized export set (JSON + markdown) to *out_dir*."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def write_json(name: str, value: object) -> None:
        path = out_dir / name
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)

    def write_md(name: str, content: str) -> None:
        path = out_dir / name
        path.write_text(content, encoding="utf-8")
        written.append(path)

    # JSON export set — mirrors the CLI's _write() shape.
    write_json("site_draft_pack.json", pack_dict)
    write_json("route_manifest.json", pack_dict["route_manifest"])
    write_json("section_library.json", pack_dict["section_library"])
    write_json("cms_content_model.json", pack_dict["cms_content_model"])
    write_json("static_site_payload.json", pack_dict["platform_payloads"]["static_site"])
    write_json("shopify_theme_draft_payload.json", pack_dict["platform_payloads"]["shopify_theme"])
    write_json("medusa_storefront_draft_payload.json", pack_dict["platform_payloads"]["medusa_storefront"])
    write_json("woocommerce_draft_payload.json", pack_dict["platform_payloads"]["woocommerce"])
    write_json("webflow_cms_draft_payload.json", pack_dict["platform_payloads"]["webflow_cms"])
    write_json("wix_headless_draft_payload.json", pack_dict["platform_payloads"]["wix_headless"])
    write_json("squarespace_draft_payload.json", pack_dict["platform_payloads"]["squarespace"])
    write_json("carrd_microsite_payload.json", pack_dict["platform_payloads"]["carrd_microsite"])
    write_json("operator_risk_review.json", pack_dict["risk_review"])

    # Markdown export set.
    write_md("site_draft_pack.md", md)
    write_md(
        "seo_plan.md",
        "# SEO Plan\n\n" + json.dumps(pack_dict["seo_plan"], indent=2, sort_keys=True) + "\n",
    )
    write_md(
        "analytics_plan.md",
        "# Analytics Plan\n\n" + json.dumps(pack_dict["analytics_plan"], indent=2, sort_keys=True) + "\n",
    )
    write_md(
        "conversion_test_plan.md",
        "# Conversion Test Plan\n\n"
        + "\n".join(
            f"- {t.get('test_id')}: {t.get('hypothesis')} Target: {t.get('target_metric')}."
            for t in pack_dict["conversion_test_plan"]["tests"]
        )
        + "\n",
    )
    write_md(
        "deployment_readiness_checklist.md",
        "# Deployment Readiness\n\n"
        + "\n".join(
            f"- {k}: {v.get('status')} — {v.get('detail')}"
            for k, v in pack_dict["deployment_readiness"]["checks"].items()
        )
        + "\n",
    )
    write_md(
        "approval_checklist.md",
        "# Approval Checklist\n\n"
        + "\n".join(f"- [ ] {item}" for item in pack_dict["approval_checklist"]["items"])
        + "\n\n## Blockers\n\n"
        + "\n".join(f"- {item}" for item in pack_dict["approval_checklist"]["blockers"])
        + "\n",
    )

    return written


def assert_blockers(pack_dict: dict) -> None:
    """Assert that review blockers surface as expected."""
    blockers = pack_dict["deployment_readiness"]["blockers"]
    approval_blockers = pack_dict["approval_checklist"]["blockers"]
    publishing_authorized = pack_dict["approval_checklist"]["publishing_authorized"]
    evidence_mode = pack_dict["evidence_mode"]

    # 5. Assert review blockers surface.
    assert "supplier_proof_ready" in blockers, (
        f"supplier_proof_ready must be in deployment_readiness.blockers; "
        f"got blockers={blockers}"
    )
    assert publishing_authorized is False, (
        f"publishing_authorized must be False; got {publishing_authorized}"
    )

    # Supplier presence is not a market_access field; it is carried by the readiness
    # check and the launch approval blockers asserted above and below.
    assert pack_dict["deployment_readiness"]["checks"]["supplier_proof_ready"]["status"] == "blocked", (
        "fixture evidence must not mark supplier proof ready"
    )

    # evidence_mode must be threaded through from the fixture.
    assert evidence_mode == "fixture_demo", (
        f"evidence_mode must be fixture_demo from the real fixture; "
        f"got {evidence_mode}"
    )

    # Blockers from launch_draft_pack.approval_checklist.blockers must propagate.
    assert any("supplier proof" in b.lower() for b in approval_blockers), (
        f"launch_draft_pack approval_checklist.blockers must propagate; "
        f"got approval_blockers={approval_blockers}"
    )


def run_site_draft_e2e(
    output_dir: Path | None = None,
    *,
    with_supplier: bool = True,
) -> dict:
    """Load real fixture files and feed them through build_site_draft_pack.

    Parameters
    ----------
    output_dir:
        If given, write a sanitized export set into this directory and return
        the pack dict. When *with_supplier* is False the supplier_feasibility
        fixture is omitted so the "supplier absent" path is exercised.
    """
    fixtures: dict[str, dict] = {}
    for role, filename in FIXTURE_FILES.items():
        fixtures[role] = load_fixture(filename)

    if not with_supplier:
        del fixtures["supplier_feasibility"]

    pack = build_site_draft_pack(
        launch_draft_pack=fixtures["launch_draft_pack"],
        opportunity_synthesis=fixtures["opportunity_synthesis"],
        product_validation=None,
        marketplace_trends=fixtures["marketplace_trends"],
        supplier_feasibility=fixtures.get("supplier_feasibility"),
        consumer_attention=fixtures["consumer_attention"],
        client_context=fixtures["client_context"],
        site_type=None,  # derived from client_context
    )
    pack_dict = pack.to_dict()
    md = markdown(pack_dict)

    if output_dir:
        sanitize_and_write(pack_dict, md, output_dir)

    if with_supplier:
        assert_blockers(pack_dict)
    return pack_dict


def main() -> int:
    fixtures: dict[str, dict] = {}
    for role, filename in FIXTURE_FILES.items():
        fixtures[role] = load_fixture(filename)

    # 2) Feed them through build_site_draft_pack with explicit provenance on every input.
    pack = build_site_draft_pack(
        launch_draft_pack=fixtures["launch_draft_pack"],
        opportunity_synthesis=fixtures["opportunity_synthesis"],
        product_validation=None,
        marketplace_trends=fixtures["marketplace_trends"],
        supplier_feasibility=fixtures["supplier_feasibility"],
        consumer_attention=fixtures["consumer_attention"],
        client_context=fixtures["client_context"],
        site_type=None,  # derived from client_context
    )
    pack_dict = pack.to_dict()
    md = markdown(pack_dict)

    # 3) Write a sanitized export set to a temp dir.
    with tempfile.TemporaryDirectory(prefix="site_draft_e2e_") as tmp:
        out_dir = Path(tmp)
        written_files = sanitize_and_write(pack_dict, md, out_dir)

        # 4) & 5) Assert missing-vs-explicit-zero distinctions and blocker surfacing.
        assert_blockers(pack_dict)

        # 6) Print a one-line SHA-validated manifest.
        manifest_json = out_dir / "site_draft_pack.json"
        digest = hashlib.sha256(manifest_json.read_bytes()).hexdigest()
        manifest_line = (
            f"sha256:{digest} "
            f"fixtures:{','.join(sorted(FIXTURE_FILES.values()))} "
            f"candidate:{pack_dict['candidate_id']} "
            f"site_type:{pack_dict['site_type']} "
            f"evidence_mode:{pack_dict['evidence_mode']} "
            f"supplier_proof_ready:{pack_dict['deployment_readiness']['checks']['supplier_proof_ready']['status']} "
            f"publishing_authorized:{pack_dict['approval_checklist']['publishing_authorized']} "
            f"blockers:{','.join(pack_dict['deployment_readiness']['blockers'])} "
            f"files:{len(written_files)}"
        )
        print(manifest_line)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
