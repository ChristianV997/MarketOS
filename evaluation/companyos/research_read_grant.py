"""Read-only research-data grant contract for CompanyOS.

A read grant is the only shape that could later authorize one bounded research
read. This module is a decision seam, not a runtime gate: it states what a grant
must bind to and evaluates a request against the canonical approval policy,
provider capability, and credential metadata.

It never reads a secret, calls a provider, persists a grant, or enables a
runtime path. Authority to verify grants and count usage belongs to a trusted
server-side approval authority that this repository does not implement. Without
one, every decision is ``not_wired`` or ``blocked``; nothing here can reach
``contract_satisfied`` on its own.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping, Protocol

from .approval_ledger import default_approval_policies
from .credential_registry import CredentialReference, ProviderCapability, _secret_like

# Only web acquisition has a canonical "approval possible later" policy for a read.
# provider_call, outreach, payment, publish, order, and spend types stay outside.
READ_REQUEST_TYPES = frozenset({"web_data_acquisition"})
READ_SIDE_EFFECTS = frozenset({"read", "network_read"})
READ_ACTION_MODES = frozenset({"read_only", "reference_only"})
READ_PURPOSES = frozenset({"market_research", "evidence_review"})
ACTIVE_CREDENTIAL_STATUS = "active_reference_only"
MAX_RETENTION_DAYS = 30
MAX_GRANT_TTL = timedelta(days=7)
DECISION_STATUSES = ("contract_satisfied", "blocked", "not_wired")
RUNTIME_STATUS = "not_wired"
DECISION_REASONS = frozenset({
    "request_type_not_grantable", "side_effect_not_read_only", "unknown_request_type",
    "blocked_by_canonical_policy", "policy_mismatch", "approver_role_invalid", "approver_missing",
    "workspace_mismatch", "approval_record_missing", "approval_binding_mismatch",
    "provider_mismatch", "capability_missing", "capability_mismatch", "capability_not_read_only",
    "credential_reference_missing", "credential_mismatch", "credential_not_active",
    "scope_not_in_credential", "scope_not_read_only", "scope_not_granted",
    "fields_required", "field_not_granted", "region_not_granted", "purpose_not_granted",
    "terms_review_missing", "privacy_review_missing", "retention_policy_invalid",
    "grant_ttl_exceeded", "grant_not_yet_valid", "grant_expired", "grant_revoked",
    "budget_per_run_exceeded", "rate_per_request_exceeded", "grant_authority_not_wired",
    "grant_authority_unavailable", "grant_not_server_verified", "budget_monthly_exceeded",
    "rate_window_exceeded",
})
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}")


def _token_ok(value: Any) -> bool:
    return isinstance(value, str) and _TOKEN.fullmatch(value) is not None


def _check_inputs(values: Mapping[str, Any]) -> None:
    """Reject malformed or secret-like identifiers without echoing them back."""
    for value in values.values():
        for item in value if isinstance(value, tuple) else (value,):
            if item in ("", None):
                continue
            if not _token_ok(item):
                raise ValueError("grant input contains a malformed identifier")
    if _secret_like(values):
        raise ValueError("secret-like grant input is not accepted")


def _aware(value: Any) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError("timestamps must be ISO-8601 strings")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("timestamp is malformed") from None


@dataclass(frozen=True)
class ReadGrant:
    """Bounds a server-issued, human-approved read. This is data; it grants nothing by itself."""

    grant_id: str
    workspace_id: str
    approval_request_id: str
    policy_id: str
    provider_id: str
    capability_id: str
    credential_id: str
    scope_ids: tuple[str, ...]
    fields: tuple[str, ...]
    regions: tuple[str, ...]
    purpose: str
    max_cost_per_run: float
    max_monthly_cost: float
    max_requests_per_window: int
    window_seconds: int
    terms_review_ref: str
    privacy_review_ref: str
    retention_days: int
    issued_at: datetime
    expires_at: datetime
    approver_id: str
    approver_role: str
    revoked_at: datetime | None = None
    revocation_ref: str = ""

    def __post_init__(self) -> None:
        if not self.grant_id:
            raise ValueError("grant_id is required")
        _check_inputs({
            "grant_id": self.grant_id, "workspace_id": self.workspace_id,
            "approval_request_id": self.approval_request_id, "policy_id": self.policy_id,
            "provider_id": self.provider_id, "capability_id": self.capability_id,
            "credential_id": self.credential_id, "scope_ids": self.scope_ids, "fields": self.fields,
            "regions": self.regions, "purpose": self.purpose, "terms_review_ref": self.terms_review_ref,
            "privacy_review_ref": self.privacy_review_ref, "approver_id": self.approver_id,
            "approver_role": self.approver_role, "revocation_ref": self.revocation_ref,
        })
        if not all(isinstance(value, tuple) for value in (self.scope_ids, self.fields, self.regions)):
            raise ValueError("grant bounds must be tuples")
        _aware(self.issued_at)
        _aware(self.expires_at)
        if self.revoked_at is not None:
            _aware(self.revoked_at)
        if self.expires_at <= self.issued_at:
            raise ValueError("grant expiry must follow issue time")
        if min(self.max_cost_per_run, self.max_monthly_cost) < 0 or self.max_requests_per_window < 0 or self.window_seconds <= 0:
            raise ValueError("grant budget and rate bounds must be non-negative")


@dataclass(frozen=True)
class ReadRequest:
    """One proposed read. Every field is untrusted input until the decision checks it."""

    approval_request_id: str
    workspace_id: str
    request_type: str
    side_effect_type: str
    provider_id: str
    capability_id: str
    scope_id: str
    fields: tuple[str, ...]
    region: str
    purpose: str
    estimated_cost: float
    requested_calls: int = 1

    def __post_init__(self) -> None:
        _check_inputs({
            "approval_request_id": self.approval_request_id, "workspace_id": self.workspace_id,
            "request_type": self.request_type, "side_effect_type": self.side_effect_type,
            "provider_id": self.provider_id, "capability_id": self.capability_id,
            "scope_id": self.scope_id, "fields": self.fields, "region": self.region, "purpose": self.purpose,
        })
        if not isinstance(self.fields, tuple):
            raise ValueError("request fields must be a tuple")
        if self.estimated_cost < 0 or self.requested_calls < 0:
            raise ValueError("request cost and call counts must be non-negative")


@dataclass(frozen=True)
class GrantUsage:
    """Usage counted by the trusted authority, never by the request."""

    spent_this_month: float
    calls_in_window: int


class GrantAuthority(Protocol):
    """Trusted server-side source of grant provenance and usage. Not implemented in this repository."""

    def verify(self, grant: ReadGrant, *, now: datetime) -> bool: ...

    def usage(self, grant: ReadGrant, *, now: datetime) -> GrantUsage: ...


@dataclass(frozen=True)
class ReadGrantDecision:
    status: str
    reasons: tuple[str, ...]
    grant_id: str
    provider_id: str
    request_type: str
    external_call_performed: bool = False
    runtime_status: str = RUNTIME_STATUS

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status, "reasons": list(self.reasons), "grant_id": self.grant_id,
            "provider_id": self.provider_id, "request_type": self.request_type,
            "external_call_performed": self.external_call_performed, "runtime_status": self.runtime_status,
        }


def _policy_for(request_type: str):
    return next((policy for policy in default_approval_policies() if policy.request_type == request_type), None)


def evaluate_read_grant(request: ReadRequest, grant: ReadGrant, *, verified_workspace_id: str,
                        credential: CredentialReference | None, capability: ProviderCapability | None,
                        now: datetime, authority: GrantAuthority | None = None) -> ReadGrantDecision:
    """Check every binding and report all failures. Policy failures are reasons, not exceptions."""
    _aware(now)
    policy = _policy_for(request.request_type)
    reasons: list[str] = []

    if request.request_type not in READ_REQUEST_TYPES:
        reasons.append("request_type_not_grantable")
    if request.side_effect_type not in READ_SIDE_EFFECTS:
        reasons.append("side_effect_not_read_only")
    if policy is None:
        reasons.append("unknown_request_type")
    else:
        if policy.blocked_in_current_mode:
            reasons.append("blocked_by_canonical_policy")
        if grant.policy_id != policy.policy_id:
            reasons.append("policy_mismatch")
        if grant.approver_role != policy.required_approver_role:
            reasons.append("approver_role_invalid")
    if not grant.approver_id:
        reasons.append("approver_missing")

    if not verified_workspace_id or not (verified_workspace_id == grant.workspace_id == request.workspace_id):
        reasons.append("workspace_mismatch")
    if not grant.approval_request_id:
        reasons.append("approval_record_missing")
    elif grant.approval_request_id != request.approval_request_id:
        reasons.append("approval_binding_mismatch")

    if grant.provider_id != request.provider_id:
        reasons.append("provider_mismatch")
    if capability is None:
        reasons.append("capability_missing")
    else:
        if (capability.capability_id != grant.capability_id or capability.provider_id != grant.provider_id
                or request.capability_id != grant.capability_id or request.request_type not in capability.approval_types):
            reasons.append("capability_mismatch")
        if capability.action_mode not in READ_ACTION_MODES:
            reasons.append("capability_not_read_only")

    if credential is None:
        reasons.append("credential_reference_missing")
    else:
        if credential.credential_id != grant.credential_id or credential.provider_id != grant.provider_id:
            reasons.append("credential_mismatch")
        if credential.status != ACTIVE_CREDENTIAL_STATUS:
            reasons.append("credential_not_active")
        scope = next((item for item in credential.permission_scopes if item.scope_id == request.scope_id), None)
        if scope is None:
            reasons.append("scope_not_in_credential")
        elif scope.action_mode not in READ_ACTION_MODES:
            reasons.append("scope_not_read_only")
    if request.scope_id not in grant.scope_ids:
        reasons.append("scope_not_granted")

    if not request.fields:
        reasons.append("fields_required")
    elif not set(request.fields) <= set(grant.fields):
        reasons.append("field_not_granted")
    if request.region not in grant.regions:
        reasons.append("region_not_granted")
    if request.purpose != grant.purpose or grant.purpose not in READ_PURPOSES:
        reasons.append("purpose_not_granted")

    if not grant.terms_review_ref:
        reasons.append("terms_review_missing")
    if not grant.privacy_review_ref:
        reasons.append("privacy_review_missing")
    if not 1 <= grant.retention_days <= MAX_RETENTION_DAYS:
        reasons.append("retention_policy_invalid")

    if grant.expires_at - grant.issued_at > MAX_GRANT_TTL:
        reasons.append("grant_ttl_exceeded")
    if now < grant.issued_at:
        reasons.append("grant_not_yet_valid")
    if now >= grant.expires_at:
        reasons.append("grant_expired")
    if grant.revoked_at is not None:
        reasons.append("grant_revoked")

    # Canonical caps are ceilings. A zero policy cap means zero spend, regardless of the grant.
    per_run_cap = min(grant.max_cost_per_run, policy.budget_cap.per_run) if policy else 0.0
    monthly_cap = min(grant.max_monthly_cost, policy.budget_cap.monthly) if policy else 0.0
    if request.estimated_cost > per_run_cap:
        reasons.append("budget_per_run_exceeded")
    if request.requested_calls > grant.max_requests_per_window:
        reasons.append("rate_per_request_exceeded")

    if authority is None:
        reasons.append("grant_authority_not_wired")
    else:
        try:
            verified_grant = authority.verify(grant, now=now)
            usage = authority.usage(grant, now=now)
        except Exception:  # fail closed; the reason code is the only report
            reasons.append("grant_authority_unavailable")
        else:
            if not verified_grant:
                reasons.append("grant_not_server_verified")
            if usage.spent_this_month + request.estimated_cost > monthly_cap:
                reasons.append("budget_monthly_exceeded")
            if usage.calls_in_window + request.requested_calls > grant.max_requests_per_window:
                reasons.append("rate_window_exceeded")

    unique = tuple(dict.fromkeys(reasons))
    if unique == ("grant_authority_not_wired",):
        status = "not_wired"
    elif unique:
        status = "blocked"
    else:
        status = "contract_satisfied"
    return ReadGrantDecision(status, unique, grant.grant_id, request.provider_id, request.request_type)


def authorize_research_read(request: ReadRequest, grant: ReadGrant, *, verified_workspace_id: str,
                            credential: CredentialReference | None, capability: ProviderCapability | None,
                            now: datetime) -> ReadGrantDecision:
    """Runtime entry point. No grant store or authority is wired, so it never returns contract_satisfied."""
    return evaluate_read_grant(request, grant, verified_workspace_id=verified_workspace_id,
                               credential=credential, capability=capability, now=now, authority=None)


def _from_mapping(cls: type, item: Mapping[str, Any]) -> Any:
    names = {field.name for field in dataclasses.fields(cls)}
    if not isinstance(item, Mapping) or set(item) - names:
        raise ValueError("payload contains unsupported fields")
    kwargs: dict[str, Any] = {}
    for field in dataclasses.fields(cls):
        if field.name not in item:
            if field.default is dataclasses.MISSING:
                raise ValueError("payload is incomplete")
            continue
        value = item[field.name]
        if field.name.endswith("_at") and value is not None:
            value = _parse_time(value)
        if isinstance(value, list):
            value = tuple(value)
        kwargs[field.name] = value
    return cls(**kwargs)


def read_grant_from_mapping(item: Mapping[str, Any]) -> ReadGrant:
    """Strict import of a grant payload. The payload is data only: it cannot carry approval or authority."""
    return _from_mapping(ReadGrant, item)


def read_request_from_mapping(item: Mapping[str, Any]) -> ReadRequest:
    return _from_mapping(ReadRequest, item)


__all__ = [
    "ACTIVE_CREDENTIAL_STATUS", "DECISION_REASONS", "DECISION_STATUSES", "GrantAuthority", "GrantUsage",
    "MAX_GRANT_TTL", "MAX_RETENTION_DAYS", "READ_ACTION_MODES", "READ_PURPOSES", "READ_REQUEST_TYPES",
    "READ_SIDE_EFFECTS", "RUNTIME_STATUS", "ReadGrant", "ReadGrantDecision", "ReadRequest",
    "authorize_research_read", "evaluate_read_grant", "read_grant_from_mapping", "read_request_from_mapping",
]
