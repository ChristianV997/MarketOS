#!/usr/bin/env python3
"""Local, dry-run client-service intake bridge.

Reads one bounded, operator-supplied sanitized JSON file (optionally paired
with a CSV data-quality-field table) describing a prospective B2B service
engagement, and drives it through the existing, canonical
``evaluation.companyos.service_delivery`` authority:

    intake (create_engagement)
        -> screening (transition_engagement)
        -> data-quality assessment (assess_client_data_quality)
        -> eligible / data_inadequate (transition_engagement)
        -> economics (evaluate_engagement_economics, canonical kernel only)
        -> client-safe deliverable (build_client_service_deliverable,
           which itself runs the real TrustOS check_workspace_leakage
           boundary and redacts before this script ever sees the result)

This is a thin composition script, not a second authority. It does not:
    - create a second service catalog, financial engine, CRM, client
      database, API client, or self-service SaaS surface;
    - reimplement service economics (evaluate_engagement_economics is a
      pure pass-through to backend.economics.kernel.calculate_service_economics);
    - reimplement TrustOS's client-safe export boundary
      (build_client_service_deliverable already calls check_workspace_leakage);
    - add a POST endpoint or any live persistence beyond the two existing,
      already-reviewed local JSON-file registries this codebase already
      uses for exactly this purpose (WorkspaceRegistry, DeliverableRegistry).

Safety, enforced by this script (on top of, not instead of, the underlying
authority's own checks):
    - Never persists raw client business data anywhere. The only thing
      this script ever writes to disk is (a) the ClientWorkspace identity
      record (name/type/mode -- no business figures) via the existing
      WorkspaceRegistry, and (b) the already-redacted, already
      leakage-checked client-safe deliverable via the existing
      DeliverableRegistry -- both existing, already-reviewed local state
      files, never a new persistence primitive.
    - Refuses to proceed without explicit consent metadata naming what the
      client agreed to (consent.granted=true and a non-empty
      consent.scope) -- a policy gate this script adds; the underlying
      authority itself has no consent concept, so this bridge does not
      silently assume it.
    - Recursively scans the entire raw intake file for secret-shaped
      strings before constructing anything (in addition to
      create_engagement's own narrower check on scope/intake_data).
    - Never defaults an unassessed client to "eligible": the state machine
      is always driven intake -> screening -> {eligible|data_inadequate}
      via the real assess_client_data_quality() result, never skipped.
    - Currency and tax-inclusion state are read verbatim from the intake
      file (default "unknown", never assumed inclusive/exclusive) and are
      never converted -- a currency mismatch raises CurrencyMismatchError,
      surfaced as a blocker, never silently coerced.
    - CoderOS is never initialized by this script.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.deliverables.registry import DeliverableRegistry  # noqa: E402
from backend.economics import CurrencyMismatchError, EconomicsError, EvidenceRef, Money  # noqa: E402
from backend.workspaces.client_workspace import ClientWorkspace  # noqa: E402
from backend.workspaces.registry import WorkspaceRegistry  # noqa: E402
from evaluation.companyos.service_delivery import (  # noqa: E402
    REQUIRED_CLIENT_DATA_FIELDS,
    assess_client_data_quality,
    build_client_service_deliverable,
    create_engagement,
    default_service_delivery_packages,
    evaluate_engagement_economics,
    transition_engagement,
)

SCHEMA = "MarketOS.ClientServiceIntake.v1"
CLASSIFICATIONS = frozenset({"eligible", "data_inadequate", "blocked", "malformed"})

# Mirrors evaluation.companyos.service_delivery's own private
# _SECRET_SHAPE_MARKERS (not imported -- that name is intentionally
# module-private) so this script's secret-shape guard behaves consistently
# with the underlying authority's, without depending on its private
# implementation detail.
_SECRET_SHAPE_MARKERS = ("ghp_", "gho_", "ghu_", "ghs_", "ghr_", "-----begin", "bearer ")
# "sk-" is a credential prefix only when it starts a token; it is also the tail of words such as
# desk-clamp-lamp or risk-review-pack, so it must not follow a letter or digit. A URL-escape (%3d) or a
# literal backslash escape (\\n) before it still counts as a boundary.
_SK_PREFIX = re.compile(r"(?<![a-z0-9])sk-|(?<=%[0-9a-f]{2})sk-|(?<=\\[nrt])sk-")


class IntakeError(ValueError):
    """A bounded, fail-closed intake rejection. Never a crash."""


def _reject_secret_shaped_recursive(value: Any, *, field_name: str) -> None:
    if isinstance(value, str):
        lowered = value.lower()
        if _SK_PREFIX.search(lowered) or any(marker in lowered for marker in _SECRET_SHAPE_MARKERS):
            raise IntakeError(f"secret-shaped value rejected in {field_name}")
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _reject_secret_shaped_recursive(item, field_name=f"{field_name}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_secret_shaped_recursive(item, field_name=f"{field_name}[{index}]")


def load_intake_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise IntakeError(f"intake file does not exist: {path}")
    text = path.read_text(encoding="utf-8")
    if text.lstrip().lower().startswith(("<", "<!doctype")):
        raise IntakeError("HTML intake files are rejected")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise IntakeError(f"malformed JSON intake file: {exc}") from exc
    if not isinstance(raw, dict):
        raise IntakeError("intake file root must be an object")
    if raw.get("schema") != SCHEMA:
        raise IntakeError(f"unsupported intake schema: {raw.get('schema')!r}")
    return raw


def load_data_quality_csv(path: Path) -> dict[str, dict[str, Any]]:
    """Bounded CSV alternative to a JSON data_fields block.

    Expected columns: field, available, as_of_days_ago, conflicting.
    Only rows naming one of REQUIRED_CLIENT_DATA_FIELDS are read; any other
    row is rejected outright rather than silently ignored, so a malformed
    or unexpected column layout fails closed instead of producing a
    quietly-incomplete assessment.
    """
    if not path.is_file():
        raise IntakeError(f"data-quality CSV does not exist: {path}")
    fields: dict[str, dict[str, Any]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not {"field", "available"}.issubset(reader.fieldnames):
            raise IntakeError("data-quality CSV must have at least 'field' and 'available' columns")
        for row in reader:
            name = (row.get("field") or "").strip()
            if not name:
                continue
            if name not in REQUIRED_CLIENT_DATA_FIELDS:
                raise IntakeError(f"unknown data-quality field in CSV: {name!r}")
            _reject_secret_shaped_recursive(row, field_name=f"data_quality_csv.{name}")
            entry: dict[str, Any] = {"available": str(row.get("available", "")).strip().lower() in {"1", "true", "yes"}}
            age = (row.get("as_of_days_ago") or "").strip()
            if age:
                try:
                    age_value = float(age)
                except ValueError:
                    raise IntakeError(f"non-numeric as_of_days_ago for field {name!r}: {age!r}") from None
                # float() accepts "nan"/"inf"/"-inf" without raising, and
                # assess_client_data_quality's own staleness check
                # (`age > max_age_days`) is silently False for NaN --
                # verified directly (float("nan") > 90.0 is False) -- so an
                # unparseable-looking value would otherwise pass through as
                # quietly "fresh" data instead of being rejected.
                if not (age_value == age_value and abs(age_value) != float("inf")):
                    raise IntakeError(f"non-finite as_of_days_ago for field {name!r}: {age!r}")
                entry["as_of_days_ago"] = age_value
            conflicting = (row.get("conflicting") or "").strip().lower()
            if conflicting:
                entry["conflicting"] = conflicting in {"1", "true", "yes"}
            fields[name] = entry
    return fields


def _require_consent(raw: Mapping[str, Any]) -> dict[str, Any]:
    consent = raw.get("consent")
    if not isinstance(consent, Mapping) or consent.get("granted") is not True or not str(consent.get("scope") or "").strip():
        raise IntakeError(
            "intake refused: consent.granted must be true and consent.scope must be a non-empty "
            "description of what the client agreed to have analyzed"
        )
    return dict(consent)


def _money_from(raw: Mapping[str, Any] | None, *, field_name: str) -> Money | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping) or "amount" not in raw or "currency" not in raw:
        raise IntakeError(f"{field_name} must be an object with 'amount' and 'currency'")
    try:
        return Money(
            str(raw["amount"]), str(raw["currency"]),
            source=str(raw.get("source", "client_intake")),
            provenance=str(raw.get("provenance", "manual_import")),
            tax_inclusion_state=str(raw.get("tax_inclusion_state", "unknown")),
            evidence_state=str(raw.get("evidence_state", "unknown")),
        )
    except (InvalidOperation, EconomicsError) as exc:
        # Money.__post_init__ raises kernel.EconomicsError for an invalid
        # amount/currency, not InvalidOperation -- caught here so a
        # malformed economics field is a reported blocker, never an
        # uncaught kernel-internal exception type leaking out of this
        # bridge (verified directly: a plain InvalidOperation catch alone
        # let "not-a-number" crash this function).
        raise IntakeError(f"{field_name}.amount is not a valid number") from exc


def _decimal_from(raw: Any, *, field_name: str) -> Decimal:
    try:
        return Decimal(str(raw))
    except InvalidOperation as exc:
        raise IntakeError(f"{field_name} is not a valid number") from exc


def _evidence_refs_from(raw: Any) -> tuple[EvidenceRef, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise IntakeError("evidence must be a list of objects")
    refs: list[EvidenceRef] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping) or not item.get("evidence_id"):
            raise IntakeError(f"evidence[{index}] must be an object with an evidence_id")
        refs.append(
            EvidenceRef(
                evidence_id=str(item["evidence_id"]),
                source_type=str(item.get("source_type", "unknown")),
                source_url=str(item.get("source_url", "")),
                document_ref=str(item.get("document_ref", "")),
                captured_at=str(item.get("captured_at", "")),
                extraction_method=str(item.get("extraction_method", "unknown")),
                evidence_state=str(item.get("evidence_state", "unknown")),
                human_confirmed=bool(item.get("human_confirmed", False)),
            )
        )
    return tuple(refs)


def run(
    raw: Mapping[str, Any],
    *,
    data_quality_override: Mapping[str, Any] | None = None,
    workspace_registry: WorkspaceRegistry | None = None,
    deliverable_registry: DeliverableRegistry | None = None,
    generated_at: str = "offline-deterministic",
) -> dict[str, Any]:
    """Drive one intake through the real service-delivery lifecycle.

    Returns a bridge-level report; never raises for a data-quality or
    economics problem (those are real, expected outcomes, reported as
    "data_inadequate"/"blocked"), only for a structurally invalid intake
    file (IntakeError, caught by main() and reported as "malformed").

    The secret-shape scan runs here, over the whole raw intake mapping,
    rather than only in load_intake_file(): run() is also a direct,
    documented entry point (e.g. for a caller that already has a parsed
    dict), and it must fail closed on its own rather than depend on every
    caller having gone through the file loader first.
    """
    _reject_secret_shaped_recursive(raw, field_name="intake")
    consent = _require_consent(raw)
    if workspace_registry is None or deliverable_registry is None:
        raise IntakeError(
            "explicit workspace and deliverable registries are required; "
            "callers must not implicitly write to shared registries"
        )

    client_id = str(raw.get("client_id") or "")
    package_id = str(raw.get("package_id") or "")
    scope = str(raw.get("scope") or "")
    if not client_id or not package_id or not scope:
        raise IntakeError("client_id, package_id, and scope are all required")

    packages = {package.package_id: package for package in default_service_delivery_packages()}
    if package_id not in packages:
        raise IntakeError(f"unknown package_id: {package_id!r} (expected one of {sorted(packages)})")
    package = packages[package_id]

    workspace_name = str(raw.get("workspace_name") or client_id)
    registry = workspace_registry
    workspace = registry.by_name(workspace_name)
    if workspace is None:
        workspace = registry.register(ClientWorkspace(name=workspace_name, workspace_type="client_service", dry_run_default=True))
    elif workspace.workspace_type != "client_service":
        raise IntakeError(f"workspace {workspace_name!r} already exists with workspace_type={workspace.workspace_type!r}, not client_service")

    data_fields = data_quality_override if data_quality_override is not None else raw.get("data_fields")
    if not isinstance(data_fields, Mapping):
        raise IntakeError("data_fields must be supplied, either in the JSON or via --data-quality-csv")

    engagement = create_engagement(client_id=client_id, workspace=workspace, package=package, scope=scope, intake_data=data_fields, created_at=generated_at)
    engagement = transition_engagement(engagement, "screening", updated_at=generated_at)

    assessment = assess_client_data_quality(data_fields, max_age_days=float(raw.get("max_age_days", 90.0)))
    next_state = "data_inadequate" if assessment.data_inadequate else "eligible"
    engagement = transition_engagement(
        engagement, next_state, updated_at=generated_at,
        data_quality_state=assessment.status, missing_information=tuple(assessment.missing_fields),
    )

    economics = None
    economics_error: str | None = None
    if not assessment.data_inadequate:
        economics = _try_build_economics(raw.get("economics_inputs") or {}, raw.get("evidence"), package)
        if isinstance(economics, str):
            economics_error, economics = economics, None
            # The client's own data was genuinely adequate, but this
            # engagement still cannot proceed (malformed/mismatched
            # economics_inputs, an operator-side input problem, not a
            # client-data-quality one) -- transition out of "eligible" so
            # lifecycle_state never claims a state a downstream consumer
            # could read as cleared to advance while classification says
            # "blocked". "paused" (not "data_inadequate"/"rejected") is
            # correct here: the client's data was fine, an input needs
            # fixing and retrying, not more client evidence or a rejection.
            engagement = transition_engagement(
                engagement, "paused", updated_at=generated_at,
                missing_information=engagement.missing_information + (f"economics_input_error:{economics_error}",),
            )

    deliverable = build_client_service_deliverable(
        engagement, package, economics, assessment,
        assumptions=tuple(str(item) for item in raw.get("assumptions", ())),
        limitations=tuple(str(item) for item in raw.get("limitations", ())),
        generated_at=generated_at,
        registry=deliverable_registry,
    )

    classification = "blocked" if economics_error else next_state
    assert classification in CLASSIFICATIONS, f"unreachable classification: {classification!r}"
    return {
        "schema": "MarketOS.ClientServiceIntakeResult.v1",
        "generated_at": generated_at,
        "classification": classification,
        "consent_scope": consent["scope"],
        "engagement_id": engagement.engagement_id,
        "workspace_id": workspace.workspace_id,
        "package_id": package_id,
        "lifecycle_state": engagement.lifecycle_state,
        "data_quality": assessment.to_dict(),
        "economics_error": economics_error,
        "deliverable": deliverable.to_dict() if hasattr(deliverable, "to_dict") else deliverable.__dict__,
        "next_action": (
            "Collect the missing/stale/conflicting evidence named in data_quality, then resubmit intake."
            if assessment.data_inadequate
            else "Review the client-safe deliverable below with a human before any client communication."
        ),
        "rollback": (
            "No external action was taken. This run writes local workspace and deliverable registry state. "
            "The default CLI paths are temporary and removed when the process exits; explicitly supplied "
            "registry paths persist. Do not delete shared registry files to roll back; use isolated paths "
            "for disposable runs."
        ),
        "read_only": False,
        "network_calls": False,
        "mutated": True,
        "mutation_scope": "local_workspace_and_deliverable_registries",
        "external_actions": False,
    }


def _try_build_economics(raw: Any, evidence: Any, package) -> Any:
    """Returns a ServiceEconomics, or a str error message on a real,
    expected failure (currency mismatch, malformed numeric field, or an
    otherwise-invalid kernel input such as a non-finite ROAS or an
    unrecognized evidence_state) -- never raises for those, since a bad
    economics input on an otherwise eligible client is a reportable
    blocker, not a crash. ``evidence`` is the intake file's top-level
    "evidence" field, passed explicitly rather than read from ``raw``
    (which is economics_inputs, a different, sibling object -- reading
    "evidence" off ``raw`` silently found nothing and dropped every
    caller-supplied evidence reference until this was caught by review)."""
    if not isinstance(raw, Mapping):
        return "economics_inputs is required once a client is eligible"
    try:
        fee = _money_from(raw.get("fee"), field_name="economics_inputs.fee")
        ad_spend = _money_from(raw.get("ad_spend"), field_name="economics_inputs.ad_spend")
        cac_before = _money_from(raw.get("cac_before"), field_name="economics_inputs.cac_before")
        cac_after = _money_from(raw.get("cac_after"), field_name="economics_inputs.cac_after")
        if fee is None or ad_spend is None or cac_before is None or cac_after is None:
            return "economics_inputs.fee/ad_spend/cac_before/cac_after are all required"
        return evaluate_engagement_economics(
            package, fee=fee, ad_spend=ad_spend,
            roas_before=_decimal_from(raw.get("roas_before", "0"), field_name="economics_inputs.roas_before"),
            roas_after=_decimal_from(raw.get("roas_after", "0"), field_name="economics_inputs.roas_after"),
            cac_before=cac_before, cac_after=cac_after,
            labor_cost=_money_from(raw.get("labor_cost"), field_name="economics_inputs.labor_cost"),
            contractor_cost=_money_from(raw.get("contractor_cost"), field_name="economics_inputs.contractor_cost"),
            tooling_cost=_money_from(raw.get("tooling_cost"), field_name="economics_inputs.tooling_cost"),
            pass_through_cost=_money_from(raw.get("pass_through_cost"), field_name="economics_inputs.pass_through_cost"),
            refund_revision_reserve=_money_from(raw.get("refund_revision_reserve"), field_name="economics_inputs.refund_revision_reserve"),
            delivery_hours=_decimal_from(raw["delivery_hours"], field_name="economics_inputs.delivery_hours") if raw.get("delivery_hours") is not None else None,
            capacity_hours=_decimal_from(raw["capacity_hours"], field_name="economics_inputs.capacity_hours") if raw.get("capacity_hours") is not None else None,
            evidence_refs=_evidence_refs_from(evidence),
        )
    except CurrencyMismatchError:
        return "currency mismatch across economics_inputs fields -- no conversion is performed"
    except (IntakeError, EconomicsError) as exc:
        return str(exc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--intake-json", type=Path, required=True)
    parser.add_argument("--data-quality-csv", type=Path)
    parser.add_argument(
        "--workspace-registry-path", type=Path,
        help="local registry file; explicit paths persist, omission uses a temporary isolated registry",
    )
    parser.add_argument(
        "--deliverable-registry-path", type=Path,
        help="local registry file; explicit paths persist, omission uses a temporary isolated registry",
    )
    parser.add_argument("--generated-at", default="offline-deterministic")
    args = parser.parse_args(argv)
    try:
        raw = load_intake_file(args.intake_json)
        data_quality_override = load_data_quality_csv(args.data_quality_csv) if args.data_quality_csv else None
        with tempfile.TemporaryDirectory(prefix="marketos-client-service-intake-") as temporary_registry_dir:
            temporary_root = Path(temporary_registry_dir)
            workspace_path = args.workspace_registry_path or temporary_root / "workspaces.json"
            deliverable_path = args.deliverable_registry_path or temporary_root / "deliverables.json"
            workspace_registry = WorkspaceRegistry(str(workspace_path))
            deliverable_registry = DeliverableRegistry(str(deliverable_path))
            report = run(
                raw, data_quality_override=data_quality_override, workspace_registry=workspace_registry,
                deliverable_registry=deliverable_registry, generated_at=args.generated_at,
            )
    except IntakeError as exc:
        print(json.dumps({"schema": SCHEMA, "classification": "malformed", "error": str(exc)}, indent=2))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["classification"] in {"eligible", "data_inadequate"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
