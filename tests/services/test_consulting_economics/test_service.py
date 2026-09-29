from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry
from services.consulting_economics import (
    ConsultingEconomicsReport,
    build_consulting_economics_report,
    export_client_safe_report,
    render_consulting_economics_markdown,
)


FIXTURES = Path(__file__).parents[2] / "fixtures" / "consulting_economics"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_project_report_reuses_kernel_metrics_and_is_complete():
    report = build_consulting_economics_report(fixture("project_complete.json"))

    assert isinstance(report, ConsultingEconomicsReport)
    assert report.recommendation == "acceptable"
    assert report.evidence_class == "fixture"
    base = next(item for item in report.scenarios if item.name == "base")
    assert base.economics is not None
    assert base.economics.contribution.amount == Decimal("1606")
    assert base.economics.contribution_per_hour.amount == Decimal("40.15")
    assert base.minimum_viable_price.amount == Decimal("3194")
    assert base.break_even_client_count == Decimal("1000") / Decimal("1606")
    assert base.maximum_concurrent_clients == Decimal("3")


def test_repeated_report_is_byte_identical_and_scenarios_are_stable():
    value = fixture("project_complete.json")
    first = build_consulting_economics_report(value)
    second = build_consulting_economics_report(value)

    assert first.to_dict() == second.to_dict()
    assert render_consulting_economics_markdown(first) == render_consulting_economics_markdown(second)
    assert first.fingerprint == second.fingerprint
    assert [item.name for item in first.scenarios] == ["conservative", "base", "upside", "downside"]


def test_missing_cost_is_needs_evidence_and_never_an_observed_zero():
    report = build_consulting_economics_report(fixture("retainer_missing_cost.json"))

    assert report.recommendation == "needs_evidence"
    assert "tooling_cost" in report.evidence_required
    assert "pass_through_cost" in report.evidence_required
    assert "payment_fees" in report.evidence_required
    assert "revision_support_reserve" in report.evidence_required
    assert report.to_dict()["scenarios"][1]["recommendation"] == "needs_evidence"


def test_explicit_zero_is_preserved_as_provided_zero():
    value = fixture("retainer_missing_cost.json")
    value["tooling_cost"] = {"amount": "0", "currency": "MXN", "source": "contract_scope", "provenance": "observed", "evidence_state": "observed"}
    report = build_consulting_economics_report(value)
    base = next(item for item in report.scenarios if item.name == "base")

    assert "tooling_cost" in base.explicit_zero_inputs
    assert "tooling_cost" not in base.missing_evidence


def test_negative_cost_is_blocked_without_reflecting_the_value():
    value = fixture("project_complete.json")
    value["contractor_cost"]["amount"] = "-1"
    report = build_consulting_economics_report(value)

    assert report.recommendation == "blocked"
    assert "negative contractor_cost" in report.blockers[0]
    assert "-1" not in json.dumps(report.to_dict())


def test_currency_mismatch_requires_explicit_fx_provenance():
    value = fixture("project_complete.json")
    value["tooling_cost"]["currency"] = "MXN"
    report = build_consulting_economics_report(value)
    assert report.recommendation == "blocked"
    assert "FX" in report.blockers[0]

    value["tooling_cost"]["fx"] = {"rate": "0.058", "timestamp": "2026-01-01T00:00:00Z", "uncertainty": "0", "source": "manual_fx_quote"}
    converted = build_consulting_economics_report(value)
    assert converted.recommendation != "blocked"
    assert converted.currency == "USD"


def test_capacity_and_client_value_are_separate_from_direct_economics():
    value = fixture("project_complete.json")
    value.pop("capacity_hours")
    value.pop("client_value_created")
    report = build_consulting_economics_report(value)
    base = next(item for item in report.scenarios if item.name == "base")

    assert base.recommendation == "acceptable"
    assert "capacity_metrics" in base.unavailable_metrics
    assert "client_value_multiple" in base.unavailable_metrics
    assert base.economics is not None


def test_all_service_models_are_product_agnostic():
    for model in ("project", "retainer", "milestone", "recurring"):
        value = fixture("project_complete.json")
        value["service_model"] = model
        value["offering_name"] = f"Generic {model} service"
        report = build_consulting_economics_report(value)
        assert report.service_model == model
        assert report.recommendation == "acceptable"


def test_negative_economics_are_not_presented_as_profitable():
    value = fixture("project_complete.json")
    value["package_price"]["amount"] = "1000"
    report = build_consulting_economics_report(value)
    base = next(item for item in report.scenarios if item.name == "base")
    assert base.recommendation == "below_break_even"
    assert base.economics.contribution.amount < 0


def test_over_capacity_is_blocked_even_when_cost_evidence_is_complete():
    value = fixture("project_complete.json")
    value["capacity_hours"] = "20"
    report = build_consulting_economics_report(value)
    base = next(item for item in report.scenarios if item.name == "base")

    assert base.recommendation == "blocked"
    assert base.blockers == ("delivery_hours_exceed_capacity",)


def test_offline_adapter_rejects_live_only_money_evidence():
    value = fixture("project_complete.json")
    value["package_price"]["evidence_state"] = "verified"
    report = build_consulting_economics_report(value)

    assert report.recommendation == "blocked"
    assert "live evidence" in report.blockers[0]


def test_client_safe_export_uses_existing_workspace_boundary(tmp_path: Path):
    report = build_consulting_economics_report(fixture("project_complete.json"))
    registry = WorkspaceRegistry(str(tmp_path / "workspaces.json"))
    workspace = registry.register(ClientWorkspace(workspace_id="client-consulting", name="consulting-demo"))

    exported = export_client_safe_report(report, workspace=workspace, registry=registry)

    assert exported.redaction_status == "validated_no_sensitive_fields"
    assert set(exported.payload) == {"workspace_id", "status", "blockers", "evidence_required", "approvals_required", "next_actions"}
    assert "internal_labor_cost" not in json.dumps(exported.to_dict())


def test_markdown_is_client_safe_and_declares_offline_mode():
    report = build_consulting_economics_report(fixture("project_complete.json"))
    markdown = render_consulting_economics_markdown(report)
    assert "OFFLINE DRY RUN" in markdown
    assert "guaranteed" not in markdown.lower()
    assert "internal_labor_cost" not in markdown


@pytest.mark.parametrize("model", ["project", "retainer", "milestone", "recurring"])
def test_missing_package_price_blocks_every_model(model: str):
    value = fixture("project_complete.json")
    value["service_model"] = model
    value["package_price"] = None
    report = build_consulting_economics_report(value)
    assert report.recommendation == "needs_evidence"
    assert "package_price" in report.evidence_required
