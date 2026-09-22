"""Compose existing MarketOS authorities into one consulting engagement plan."""
from __future__ import annotations

import importlib
from typing import Any, Mapping

from backend.experiments.envelope import CommercialRunEnvelope
from backend.organization.report_registry import ReportRegistry, get_report_registry
from backend.organization.service_contract import ServiceContractRegistry, get_service_contract_registry
from backend.workspaces.artifact_store import ArtifactStore
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry, get_workspace_registry
from evaluation.commerce.kernel_integration import replay_fingerprint
from evaluation.companyos.service_delivery import create_engagement, default_service_delivery_packages
from evaluation.trustos.client_workspace_isolation import export_client_evidence

from .schemas import (
    ComponentReportReference,
    ConsultingEngagementRequest,
    ConsultingEngagementResult,
    ExecutionPlanItem,
    SchemaValidationError,
)

_DEFAULT_DELIVERABLES = {
    "product": ("product_research", "customer_intelligence", "client_safe_export"),
    "service": ("service_engagement", "customer_intelligence", "client_safe_export"),
    "hybrid": ("product_research", "service_engagement", "customer_intelligence", "client_safe_export"),
    "unknown": ("client_safe_export",),
}
_DELIVERABLE_TARGETS = {
    "product_research": ("product_research", "strategy", "backend.commercial.product_research", "run_product_research"),
    "unit_economics": ("unit_economics", "finance", "services.unit_economics.analyzer", "run_unit_economics"),
    "customer_intelligence": ("customer_intelligence", "growth", "backend.commercial.customer_intelligence", "run_customer_intelligence"),
    "creative_growth": ("creative_growth", "creative", "services.creative_growth.plan", "build_creative_growth_plan"),
    "profit_stack_advisor": ("profit_stack_advisor", "finance", "backend.commercial.profit_stack_advisor", "run_profit_stack_advisor"),
    "service_engagement": ("service_engagement", "strategy", "evaluation.companyos.service_engagement", "build_service_engagement"),
    "service_delivery": ("service_delivery", "strategy", "evaluation.companyos.service_delivery", "build_service_delivery_plane_report"),
}
_CAPABILITY_SERVICES = frozenset({"product_research", "unit_economics", "customer_intelligence", "creative_growth", "profit_stack_advisor"})


class ConsultingEngagementError(ValueError):
    """Stable, non-reflective engagement boundary failure."""


def _stable_id(request: ConsultingEngagementRequest) -> str:
    return "consulting-" + replay_fingerprint({"request_fingerprint": request.fingerprint})[:24]


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _evidence_summary(request: ConsultingEngagementRequest) -> dict[str, Any]:
    class_counts: dict[str, int] = {}
    state_counts: dict[str, int] = {}
    for item in request.evidence:
        class_counts[item.evidence_class] = class_counts.get(item.evidence_class, 0) + 1
        state_counts[item.state] = state_counts.get(item.state, 0) + 1
    weak_classes = {"fixture", "manual", "manual_import", "simulated", "simulated_or_planned", "planned", "derived"}
    live_authoritative = any(item.evidence_class == "live" and item.authoritative and item.state == "available" for item in request.evidence)
    return {
        "class_counts": dict(sorted(class_counts.items())),
        "state_counts": dict(sorted(state_counts.items())),
        "live_authoritative_evidence": live_authoritative,
        "evidence_ceiling": "live_authoritative_only" if live_authoritative else "fixture_manual_simulated_or_planned",
        "launch_authorized": False,
        "external_validation": "unavailable",
        "weak_evidence_present": any(item.evidence_class in weak_classes for item in request.evidence),
    }


def _plan_item(
    deliverable: str,
    service_registry: ServiceContractRegistry,
) -> ExecutionPlanItem:
    if deliverable == "client_safe_export":
        return ExecutionPlanItem(deliverable, "trustos_export", "evaluation.trustos.client_workspace_isolation", "export_client_evidence", "ready")
    service_name, department, module_path, function_name = _DELIVERABLE_TARGETS[deliverable]
    if service_name in _CAPABILITY_SERVICES:
        validation = service_registry.validate_safe_to_call(service_name, department)
        if validation.get("allowed"):
            return ExecutionPlanItem(deliverable, service_name, module_path, function_name, "ready")
        if validation.get("status") == "unsupported_service":
            return ExecutionPlanItem(deliverable, service_name, module_path, function_name, "unavailable", "optional_capability_unavailable")
        return ExecutionPlanItem(deliverable, service_name, module_path, function_name, "blocked", "capability_requires_explicit_safe_call")
    try:
        module = importlib.import_module(module_path)
        getattr(module, function_name)
    except (ImportError, AttributeError):
        return ExecutionPlanItem(deliverable, service_name, module_path, function_name, "unavailable", "optional_capability_unavailable")
    except Exception:
        return ExecutionPlanItem(deliverable, service_name, module_path, function_name, "unavailable", "optional_capability_unavailable")
    return ExecutionPlanItem(deliverable, service_name, module_path, function_name, "ready")


def _report_references(
    request: ConsultingEngagementRequest,
    report_registry: ReportRegistry,
    workspace_id: str,
) -> tuple[ComponentReportReference, ...]:
    references: list[ComponentReportReference] = []
    for report_id in request.linked_component_report_ids:
        report = report_registry.get(report_id)
        if report is None:
            raise ConsultingEngagementError("component_report_unavailable")
        if report.workspace_id != workspace_id:
            raise ConsultingEngagementError("component_report_workspace_mismatch")
        references.append(ComponentReportReference(
            report_id=report.report_id,
            service_name=report.service_name,
            status=report.status,
            workspace_id=report.workspace_id,
            experiment_id=report.experiment_id,
        ))
    return tuple(references)


def _safe_export_payload(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "workspace_id": result["workspace_id"],
        "status": result["status"],
        "blockers": list(result["blockers"]),
        "evidence_required": list(result["missing_information"]) or ["review_evidence_provenance"],
        "approvals_required": ["client_scope_review"],
        "next_actions": [result["next_action"]],
    }


class ConsultingEngagementOrchestrator:
    """Build a deterministic read-only engagement from existing authorities."""

    def __init__(
        self,
        *,
        workspace_registry: WorkspaceRegistry | None = None,
        report_registry: ReportRegistry | None = None,
        service_contract_registry: ServiceContractRegistry | None = None,
    ) -> None:
        self.workspace_registry = workspace_registry or get_workspace_registry()
        self.report_registry = report_registry or get_report_registry()
        self.service_contract_registry = service_contract_registry or get_service_contract_registry()

    def _assert_workspace(self, workspace: ClientWorkspace, request: ConsultingEngagementRequest) -> ClientWorkspace:
        if not isinstance(workspace, ClientWorkspace):
            raise ConsultingEngagementError("workspace_identity_rejected")
        if workspace.workspace_id != request.workspace_id:
            raise ConsultingEngagementError("workspace_identity_mismatch")
        registered = self.workspace_registry.get(workspace.workspace_id)
        if registered is None or registered.to_dict() != workspace.to_dict():
            raise ConsultingEngagementError("workspace_identity_rejected")
        return registered

    def build(self, request: ConsultingEngagementRequest | Mapping[str, Any], *, workspace: ClientWorkspace) -> ConsultingEngagementResult:
        try:
            request = request if isinstance(request, ConsultingEngagementRequest) else ConsultingEngagementRequest.from_mapping(request)
        except SchemaValidationError as exc:
            raise ConsultingEngagementError(str(exc)) from None
        registered = self._assert_workspace(workspace, request)
        if registered.workspace_type != "client_service":
            raise ConsultingEngagementError("workspace_not_client_service")

        component_reports = _report_references(request, self.report_registry, registered.workspace_id)
        selected = request.selected_deliverables or _DEFAULT_DELIVERABLES[request.offering_kind]
        if request.offering_kind == "unknown":
            blockers = ["offering_kind_unknown"]
        else:
            blockers = []
        plan = tuple(_plan_item(item, self.service_contract_registry) for item in selected if item != "client_safe_export")
        blockers.extend(f"deliverable_{item.status}:{item.deliverable}" for item in plan if item.status in {"blocked", "unavailable"})
        if request.conflicts:
            blockers.append("evidence_conflict")
        if any(item.state in {"stale", "conflicting", "blocked", "unavailable"} for item in request.evidence):
            blockers.append("evidence_not_current")
        blockers.extend(f"missing_information:{item}" for item in request.missing_information)
        blockers = list(_dedupe(tuple(blockers)))

        evidence_summary = _evidence_summary(request)
        status = "blocked" if blockers else "ready_for_review"
        next_action = (
            "Resolve the listed evidence and capability blockers before client review."
            if blockers else "Review the client-safe projection; no live action or launch authorization is granted."
        )
        engagement_id = _stable_id(request)
        try:
            ArtifactStore(registered, registry=self.workspace_registry).path_for(engagement_id, "engagement.json")
        except Exception:
            raise ConsultingEngagementError("artifact_workspace_boundary_rejected") from None

        # The existing CompanyOS engagement structure is used as a compatibility
        # context; no new lifecycle or price authority is created here.
        packages = default_service_delivery_packages()
        package = next(item for item in packages if item.package_id == "product-validation-sprint")
        companyos_engagement = create_engagement(
            client_id=request.client_id,
            workspace=registered,
            package=package,
            scope=request.scope,
            intake_data={"offering_kind": request.offering_kind, "geography": request.geography},
            created_at="offline-deterministic",
        )
        envelope = CommercialRunEnvelope(
            artifact_id=engagement_id,
            experiment_id=engagement_id,
            service_name="consulting_engagement",
            workspace_id=registered.workspace_id,
            workspace=registered.workspace_id,
            mode="dry_run",
            created_at=0.0,
            inputs={"request_fingerprint": request.fingerprint},
        )

        safe_projection = {
            "engagement_id": engagement_id,
            "workspace_id": registered.workspace_id,
            "client_objective": request.client_objective,
            "geography": request.geography,
            "language": request.language,
            "scope": request.scope,
            "offering_kind": request.offering_kind,
            "selected_deliverables": list(selected),
            "status": status,
            "evidence_summary": evidence_summary,
            "assumptions": list(request.assumptions),
            "conflicts": list(request.conflicts),
            "missing_information": list(request.missing_information),
            "blockers": blockers,
            "next_action": next_action,
            "component_reports": [item.to_dict() for item in component_reports],
            "optional_upsell_recommendations": list(request.optional_upsell_recommendations),
            "read_only": True,
            "network_calls": False,
            "database_writes": False,
            "mutated": False,
        }
        export = export_client_evidence(
            workspace=registered,
            registry=self.workspace_registry,
            provenance=f"derived://consulting-engagement/{engagement_id}",
            evidence_state="requires_review",
            payload=_safe_export_payload(safe_projection),
        )
        internal_projection = {
            **safe_projection,
            "execution_plan": [item.to_dict() for item in plan],
            "companyos_engagement_id": companyos_engagement.engagement_id,
            "run_envelope": {"experiment_id": envelope.experiment_id, "replay_hash": envelope.replay_hash, "status": envelope.status},
        }
        fingerprint = replay_fingerprint(internal_projection)
        return ConsultingEngagementResult(
            engagement_id=engagement_id,
            client_id=request.client_id,
            workspace_id=registered.workspace_id,
            client_objective=request.client_objective,
            geography=request.geography,
            language=request.language,
            scope=request.scope,
            offering_kind=request.offering_kind,
            selected_deliverables=tuple(selected),
            status=status,
            evidence_summary=evidence_summary,
            assumptions=request.assumptions,
            conflicts=request.conflicts,
            missing_information=request.missing_information,
            blockers=tuple(blockers),
            next_action=next_action,
            component_reports=component_reports,
            execution_plan=plan,
            client_safe_projection=safe_projection,
            trustos_export=export.to_dict(),
            fingerprint=fingerprint,
        )


def build_consulting_engagement(
    request: ConsultingEngagementRequest | Mapping[str, Any],
    *,
    workspace: ClientWorkspace,
    workspace_registry: WorkspaceRegistry | None = None,
    report_registry: ReportRegistry | None = None,
    service_contract_registry: ServiceContractRegistry | None = None,
) -> ConsultingEngagementResult:
    return ConsultingEngagementOrchestrator(
        workspace_registry=workspace_registry,
        report_registry=report_registry,
        service_contract_registry=service_contract_registry,
    ).build(request, workspace=workspace)


def render_consulting_engagement_markdown(result: ConsultingEngagementResult) -> str:
    return result.to_markdown()
