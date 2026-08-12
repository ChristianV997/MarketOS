"""Fail-closed, offline TrustOS gate evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from evaluation.companyos.approval_ledger import REQUEST_TYPES

from .control_plane import ACTION_CATEGORIES, GATE_BEHAVIORS, TrustGateResult, _clean


@dataclass(frozen=True)
class TrustGateInput:
    action: str
    target: str = "offline-simulation"
    evidence_refs: tuple[str, ...] = ()
    approval_ids: tuple[str, ...] = ()
    requested_budget: float = 0.0
    context: Mapping[str, Any] = None

    def __post_init__(self) -> None:
        if self.action not in ACTION_CATEGORIES:
            raise ValueError(f"unsupported TrustOS action: {self.action}")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class TrustGateContext:
    provider_registered: bool = False
    credential_reference_exists: bool = False
    secret_value_absent: bool = True
    approval_recorded: bool = False
    budget_cap_set: bool = False
    terms_review_complete: bool = False
    privacy_review_complete: bool = False
    output_contract_tested: bool = False
    security_evidence_present: bool = False
    secret_scan_clean: bool = False
    dependency_scan_clean: bool = False
    policies_present: bool = False
    incident_response_present: bool = False
    consent_verified: bool = False
    do_not_contact: bool = False
    unsubscribe_present: bool = False
    ai_disclosure_present: bool = False
    model_spend_controls: bool = False
    client_isolated: bool = False
    internal_notes_excluded: bool = False
    accounting_review: bool = False
    lawyer_review: bool = False
    founder_approval: bool = False
    uploaded_file_sanitized: bool = False
    professional_review_complete: bool = False

    @classmethod
    def from_mapping(cls, context: Mapping[str, Any] | None) -> "TrustGateContext":
        values = {key: bool(value) for key, value in dict(context or {}).items() if key in cls.__dataclass_fields__}
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class TrustGateDecision:
    decision: str
    rationale: str
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.decision not in GATE_BEHAVIORS:
            raise ValueError(f"unsupported TrustOS decision: {self.decision}")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class TrustGateBlocker:
    code: str
    message: str
    severity: str = "high"

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class TrustGateWarning:
    code: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class TrustGateExceptionRequest:
    exception_id: str
    action: str
    approver_role: str
    missing_conditions: tuple[str, ...]
    status: str = "requested"

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


class TrustGateRunner:
    """Evaluate policies only; this class has no execution method."""

    def evaluate(self, gate_input: TrustGateInput, *, generated_at: str = "offline-deterministic") -> TrustGateResult:
        return evaluate_action(gate_input.action, context=gate_input.context, generated_at=generated_at, requested_budget=gate_input.requested_budget)

    def simulate(self, action: str, *, context: Mapping[str, Any] | None = None, generated_at: str = "offline-deterministic") -> TrustGateResult:
        return evaluate_action(action, context=context, generated_at=generated_at)


def _result(action: str, decision: str, blockers: tuple[str, ...] = (), warnings: tuple[str, ...] = (), approvals: tuple[str, ...] = (), missing: tuple[str, ...] = (), generated_at: str = "offline-deterministic") -> TrustGateResult:
    return TrustGateResult(f"gate-{action}", action, decision, blockers, warnings, missing, approvals, "human_operator" if blockers else "none", generated_at, True)


def evaluate_action(action: str, *, context: Mapping[str, Any] | None = None, generated_at: str = "offline-deterministic", requested_budget: float = 0.0) -> TrustGateResult:
    if action not in ACTION_CATEGORIES:
        raise ValueError(f"unsupported TrustOS action: {action}")
    ctx = TrustGateContext.from_mapping(context)
    if action in {"activate_provider", "run_provider_readonly_call", "run_provider_write_call"}:
        missing = tuple(key for key, value in (("provider_registered", ctx.provider_registered), ("credential_reference_exists", ctx.credential_reference_exists), ("secret_value_absent", ctx.secret_value_absent), ("approval_recorded", ctx.approval_recorded), ("budget_cap_set", ctx.budget_cap_set), ("terms_review_complete", ctx.terms_review_complete), ("privacy_review_complete", ctx.privacy_review_complete), ("output_contract_tested", ctx.output_contract_tested)) if not value)
        blockers = tuple(f"{key} required" for key in missing)
        return _result(action, "hard_block" if blockers else "needs_professional_review", blockers, ("Live transport is disabled in TrustOS v1.",), ("provider_call", "web_data_acquisition"), missing, generated_at)
    if action in {"send_outbound_email", "send_customer_message"}:
        missing = tuple(key for key, value in (("consent_verified", ctx.consent_verified), ("unsubscribe_present", ctx.unsubscribe_present), ("ai_disclosure_present", ctx.ai_disclosure_present)) if not value)
        blockers = tuple(f"{key} required" for key in missing) + (("do_not_contact is true",) if ctx.do_not_contact else ())
        return _result(action, "hard_block" if blockers else "needs_professional_review", blockers, ("Message sending is disabled; this is a draft simulation only.",), ("email_send", "customer_message"), missing, generated_at)
    if action == "enable_live_model_calls":
        blockers = () if ctx.model_spend_controls and ctx.approval_recorded and ctx.budget_cap_set else ("model-spend controls, approval, and budget cap required",)
        return _result(action, "hard_block" if blockers else "needs_professional_review", blockers, ("No model calls occur in TrustOS v1.",), ("model_spend",), ("model_spend_controls",), generated_at)
    if action == "create_payment":
        return _result(action, "hard_block", ("payment creation is blocked in offline mode", "accountant review required"), (), ("payment_creation",), ("accounting_review",), generated_at)
    if action == "sync_accounting":
        return _result(action, "hard_block", ("accounting platform mutation is blocked",), (), ("accounting_sync",), (), generated_at)
    if action == "create_order":
        return _result(action, "hard_block", ("order creation is blocked", "supplier/order approval required"), (), ("supplier_order",), (), generated_at)
    if action == "launch_ad":
        return _result(action, "hard_block", ("ad launch and spend are blocked",), (), ("ad_launch",), (), generated_at)
    if action == "publish_site":
        blockers = tuple(key for key, value in (("security_evidence_present", ctx.security_evidence_present), ("policies_present", ctx.policies_present), ("incident_response_present", ctx.incident_response_present), ("approval_recorded", ctx.approval_recorded), ("lawyer_review", ctx.lawyer_review)) if not value)
        return _result(action, "hard_block" if blockers else "needs_professional_review", tuple(f"{key} required" for key in blockers), (), ("site_publish",), blockers, generated_at)
    if action == "public_beta_launch":
        missing = tuple(key for key, value in (("security_evidence_present", ctx.security_evidence_present), ("secret_scan_clean", ctx.secret_scan_clean), ("dependency_scan_clean", ctx.dependency_scan_clean), ("policies_present", ctx.policies_present), ("incident_response_present", ctx.incident_response_present), ("approval_recorded", ctx.approval_recorded), ("client_isolated", ctx.client_isolated)) if not value)
        blockers = tuple(f"{key} required" for key in missing)
        return _result(action, "hard_block", blockers, ("Legal, privacy, tax, and security professionals must review applicable materials.",), ("site_publish",), missing, generated_at)
    if action == "client_workspace_export":
        missing = tuple(key for key, value in (("client_isolated", ctx.client_isolated), ("internal_notes_excluded", ctx.internal_notes_excluded)) if not value)
        return _result(action, "hard_block" if missing else "allow", tuple(f"{key} required" for key in missing), (), ("customer_message",), missing, generated_at)
    if action == "collect_personal_data":
        missing = () if ctx.privacy_review_complete and ctx.policies_present else ("privacy controls and reviewed policy required",)
        return _result(action, "hard_block" if missing else "needs_professional_review", (missing,) if isinstance(missing, str) else missing, (), (), ("privacy_review_complete",), generated_at)
    if action == "process_uploaded_file":
        return _result(action, "needs_professional_review" if not ctx.uploaded_file_sanitized else "allow", ("uploaded file sanitization required",) if not ctx.uploaded_file_sanitized else (), (), (), ("uploaded_file_sanitized",), generated_at)
    if action == "use_credentials":
        return _result(action, "hard_block", ("credential reads are disabled; use a metadata-only reference",), (), ("provider_call",), ("credential_reference_exists",), generated_at)
    if action == "enable_public_signup":
        return _result(action, "hard_block", ("public signup requires privacy, abuse, and incident controls",), (), ("site_publish",), ("privacy_review_complete", "policies_present"), generated_at)
    return _result(action, "hard_block", ("action has no approved TrustOS execution path",), (), (), (), generated_at)


__all__ = ["TrustGateRunner", "TrustGateInput", "TrustGateContext", "TrustGateDecision", "TrustGateBlocker", "TrustGateWarning", "TrustGateExceptionRequest", "evaluate_action", "REQUEST_TYPES"]
