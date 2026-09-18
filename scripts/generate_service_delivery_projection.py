"""Generate the canonical, sanitized service-engagement projection consumed
by the read-only workbench (PR #264) via its GET route (PR #271).

Offline and deterministic: builds a handful of example engagements (one per
priority package, spanning draft-ready, data-inadequate, and a
stronger-evidence example) entirely from existing canonical authorities
(evaluation.companyos.service_delivery / service_delivery_artifact /
service_delivery_projection), then writes the resulting envelope beneath
``artifacts/`` -- the one location PR #271's route is willing to read from.

This script never calls a provider, never spends, never mutates a client
record, and never writes outside ``artifacts/``.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.deliverables.registry import DeliverableRegistry  # noqa: E402
from backend.economics import EvidenceRef, Money  # noqa: E402
from backend.workspaces.client_workspace import ClientWorkspace  # noqa: E402
from evaluation.companyos.service_delivery import (  # noqa: E402
    REQUIRED_CLIENT_DATA_FIELDS,
    assess_client_data_quality,
    build_client_service_deliverable,
    create_engagement,
    default_service_delivery_packages,
    evaluate_engagement_economics,
    transition_engagement,
)
from evaluation.companyos.service_delivery_artifact import build_service_delivery_artifact  # noqa: E402
from evaluation.companyos.service_delivery_projection import (  # noqa: E402
    build_service_engagement_projection,
    build_service_engagement_row,
)

ARTIFACTS_ROOT = (ROOT / "artifacts").resolve()


def _adequate_intake() -> dict:
    return {name: {"available": True} for name in REQUIRED_CLIENT_DATA_FIELDS}


def _draft_ready_example(package_id: str, client_id: str, registry: DeliverableRegistry) -> dict:
    packages = {p.package_id: p for p in default_service_delivery_packages()}
    pkg = packages[package_id]
    engagement = create_engagement(client_id=client_id, workspace=ClientWorkspace(name=client_id, workspace_type="client_service"), package=pkg, scope="Example engagement (fixture data)")
    for state in ("screening", "eligible", "scoped", "evidence_collection"):
        engagement = transition_engagement(engagement, state)
    refs = (EvidenceRef(f"ev-{client_id}", source_type="manual_import", evidence_state="fixture", captured_at="offline-deterministic"),)
    engagement = transition_engagement(engagement, "analysis", evidence_set=refs)
    engagement = transition_engagement(engagement, "draft_ready")
    dq = assess_client_data_quality(_adequate_intake())
    economics = evaluate_engagement_economics(
        pkg, fee=pkg.price_min_money, ad_spend=Money("2000", pkg.currency),
        roas_before=Decimal("1.2"), roas_after=Decimal("1.6"),
        cac_before=Money("30", pkg.currency), cac_after=Money("24", pkg.currency),
        evidence_refs=refs,
    )
    deliverable = build_client_service_deliverable(engagement, pkg, economics, dq, recommendation="Draft ready for internal review.", registry=registry)
    artifact = build_service_delivery_artifact(engagement, pkg, economics, dq, deliverable, evidence_refs=refs)
    return build_service_engagement_row(engagement, pkg, dq, economics, artifact)


def _data_inadequate_example(package_id: str, client_id: str, registry: DeliverableRegistry) -> dict:
    packages = {p.package_id: p for p in default_service_delivery_packages()}
    pkg = packages[package_id]
    engagement = create_engagement(client_id=client_id, workspace=ClientWorkspace(name=client_id, workspace_type="client_service"), package=pkg, scope="Example engagement (insufficient client data)")
    engagement = transition_engagement(engagement, "screening")
    dq = assess_client_data_quality({"revenue": {"available": True}})
    engagement = transition_engagement(engagement, "data_inadequate")
    deliverable = build_client_service_deliverable(engagement, pkg, None, dq, registry=registry)
    artifact = build_service_delivery_artifact(engagement, pkg, None, dq, deliverable)
    return build_service_engagement_row(engagement, pkg, dq, None, artifact)


def build_examples() -> list[dict]:
    # The deliverable registry this generator uses is a required plumbing
    # argument for build_client_service_deliverable(), not an output of
    # this script -- it is written to a throwaway temp path, never
    # committed alongside the projection artifact itself.
    registry = DeliverableRegistry(path=str(Path(tempfile.gettempdir()) / "service_delivery_projection_example_deliverables.json"))
    return [
        _draft_ready_example("product-validation-sprint", "example-client-alpha", registry),
        _data_inadequate_example("unit-economics-cac-roas-diagnostic", "example-client-beta", registry),
        _draft_ready_example("launch-draft-pack", "example-client-gamma", registry),
        _draft_ready_example("managed-acquisition-cro", "example-client-delta", registry),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(ARTIFACTS_ROOT / "service_delivery_projection.json"), help="Path beneath artifacts/ to write the projection to.")
    args = parser.parse_args(argv)

    output = Path(args.output).resolve()
    if ARTIFACTS_ROOT not in output.parents and output != ARTIFACTS_ROOT:
        parser.error("--output must resolve beneath artifacts/")

    rows = build_examples()
    projection = build_service_engagement_projection(rows, availability="manual_import", diagnostics=("generated_by_scripts/generate_service_delivery_projection.py",))

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(projection, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {len(rows)} example engagements to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
