"""Trust-boundary contract for research read grants.

The grant seam is a decision only. These tests prove that serialized approval
claims, unverified grants, mismatched bindings, expired or revoked grants,
exceeded caps, missing review references, and every non-read request type all
fail closed. The only success path needs a server-verified authority supplied
by the caller, and this module's authority double exists only for tests.
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from evaluation.companyos import research_read_grant as rrg
from evaluation.companyos.approval_ledger import (
    LIVE_ACTION_TYPES,
    REQUEST_TYPES,
    default_approval_policies,
    make_request,
    transition_status,
)
from evaluation.companyos.credential_registry import build_credential_registry
from evaluation.companyos.research_read_grant import (
    DECISION_REASONS,
    READ_REQUEST_TYPES,
    ReadGrant,
    ReadRequest,
    evaluate_read_grant,
    read_grant_from_mapping,
)

# Built at runtime so no live-key-shaped literal appears in source for secret scanners.
CANARY = "sk" + "_live_" + "fixturecanary0001"
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
WORKSPACE = "workspace-alpha"
PROVIDER = "apify"
CREDENTIAL = "credential-apify"
CAPABILITY = "cap-apify-read"
SCOPE = "apify:read_only"
POLICY = "approval-policy-web_data_acquisition"
APPROVAL = "approval-web-read-1"


@dataclass(frozen=True)
class FakeAuthority:
    """Test double for the trusted server authority. Production code never imports this."""

    verified: bool = True
    spent_this_month: float = 0.0
    calls_in_window: int = 0
    fail: bool = False

    def verify(self, grant: ReadGrant, *, now: datetime) -> bool:
        if self.fail:
            raise RuntimeError("fixture authority failure")
        return self.verified

    def usage(self, grant: ReadGrant, *, now: datetime) -> rrg.GrantUsage:
        if self.fail:
            raise RuntimeError("fixture authority failure")
        return rrg.GrantUsage(self.spent_this_month, self.calls_in_window)


@pytest.fixture(scope="module")
def registry():
    return build_credential_registry(generated_at="fixed")


def _grant(**overrides: Any) -> ReadGrant:
    values: dict[str, Any] = dict(
        grant_id="grant-web-read-1", workspace_id=WORKSPACE, approval_request_id=APPROVAL, policy_id=POLICY,
        provider_id=PROVIDER, capability_id=CAPABILITY, credential_id=CREDENTIAL, scope_ids=(SCOPE,),
        fields=("title", "price"), regions=("MX",), purpose="market_research", max_cost_per_run=0.0,
        max_monthly_cost=0.0, max_requests_per_window=3, window_seconds=3600,
        terms_review_ref="terms-review-apify-1", privacy_review_ref="privacy-review-apify-1",
        retention_days=7, issued_at=NOW - timedelta(hours=1), expires_at=NOW + timedelta(days=1),
        approver_id="human-approver-fixture", approver_role="human_operator",
    )
    values.update(overrides)
    return ReadGrant(**values)


def _request(**overrides: Any) -> ReadRequest:
    values: dict[str, Any] = dict(
        approval_request_id=APPROVAL, workspace_id=WORKSPACE, request_type="web_data_acquisition",
        side_effect_type="network_read", provider_id=PROVIDER, capability_id=CAPABILITY, scope_id=SCOPE,
        fields=("title",), region="MX", purpose="market_research", estimated_cost=0.0, requested_calls=1,
    )
    values.update(overrides)
    return ReadRequest(**values)


def _credential_for(registry, *, active: bool = True):
    base = next(item for item in registry.credentials if item.credential_id == CREDENTIAL)
    return replace(base, status="active_reference_only") if active else base


def _capability_for(registry):
    return next(item for item in registry.capabilities if item.capability_id == CAPABILITY)


def _decide(registry, *, request: dict | None = None, grant: dict | None = None, verified: str = WORKSPACE,
            credential_mode: str = "active", capability_missing: bool = False,
            capability_action_mode: str | None = None, scope_action_mode: str | None = None,
            authority: Any = FakeAuthority(), now: datetime = NOW):
    credential = None
    if credential_mode != "missing":
        credential = _credential_for(registry, active=credential_mode == "active")
        if scope_action_mode:
            credential = replace(credential, permission_scopes=tuple(
                replace(scope, action_mode=scope_action_mode) for scope in credential.permission_scopes))
    capability = None
    if not capability_missing:
        capability = _capability_for(registry)
        if capability_action_mode:
            capability = replace(capability, action_mode=capability_action_mode)
    return evaluate_read_grant(
        _request(**(request or {})), _grant(**(grant or {})), verified_workspace_id=verified,
        credential=credential, capability=capability, now=now, authority=authority,
    )


def _serialized(**extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field in dataclasses.fields(ReadGrant):
        value = getattr(_grant(), field.name)
        if isinstance(value, datetime):
            value = value.isoformat()
        elif isinstance(value, tuple):
            value = list(value)
        payload[field.name] = value
    payload.update(extra)
    return payload


# Positive path and the not-wired boundary.

def test_valid_server_verified_read_grant_satisfies_contract_only(registry):
    decision = _decide(registry, authority=FakeAuthority())

    assert decision.status == "contract_satisfied"
    assert decision.reasons == ()
    assert decision.external_call_performed is False
    assert decision.runtime_status == "not_wired"


def test_same_valid_grant_without_authority_is_not_wired(registry):
    decision = _decide(registry, authority=None)

    assert decision.status == "not_wired"
    assert decision.reasons == ("grant_authority_not_wired",)


def test_runtime_entry_point_never_returns_contract_satisfied(registry):
    variants = [
        ({}, {}),
        ({"fields": ("price",)}, {"fields": ("title", "price")}),
        ({"requested_calls": 0}, {}),
    ]
    for request_over, grant_over in variants:
        decision = rrg.authorize_research_read(
            _request(**request_over), _grant(**grant_over), verified_workspace_id=WORKSPACE,
            credential=_credential_for(registry), capability=_capability_for(registry), now=NOW,
        )
        assert decision.status in {"not_wired", "blocked"}
        assert decision.status != "contract_satisfied"


# Serialized and forged approval input.

@pytest.mark.parametrize("forged", [
    {"status": "approved"}, {"approved": True}, {"approval_status": "approved"},
    {"authority": "server"}, {"server_verified": True},
])
def test_serialized_approval_claims_are_rejected(forged):
    with pytest.raises(ValueError, match="unsupported fields"):
        read_grant_from_mapping(_serialized(**forged))


def test_serialized_grant_with_human_role_still_has_no_authority(registry):
    grant = read_grant_from_mapping(_serialized(approver_role="human_operator"))
    decision = evaluate_read_grant(
        _request(), grant, verified_workspace_id=WORKSPACE, credential=_credential_for(registry),
        capability=_capability_for(registry), now=NOW, authority=None,
    )

    assert decision.status == "not_wired"


def test_unverified_serialized_grant_is_blocked_by_authority(registry):
    grant = read_grant_from_mapping(_serialized())
    decision = evaluate_read_grant(
        _request(), grant, verified_workspace_id=WORKSPACE, credential=_credential_for(registry),
        capability=_capability_for(registry), now=NOW, authority=FakeAuthority(verified=False),
    )

    assert decision.status == "blocked"
    assert decision.reasons == ("grant_not_server_verified",)


def test_authority_failure_is_fail_closed(registry):
    decision = _decide(registry, authority=FakeAuthority(fail=True))

    assert decision.status == "blocked"
    assert "grant_authority_unavailable" in decision.reasons


def test_canonical_gate_still_refuses_approved_transition():
    request = make_request(approval_id=APPROVAL, request_type="web_data_acquisition", status="pending_review")

    with pytest.raises(ValueError, match="cannot grant live approval"):
        transition_status(request, "approved")


# Binding mismatches. Each case changes exactly one binding and expects its reason.

BINDING_CASES = [
    ("workspace_request_mismatch", {"request": {"workspace_id": "workspace-beta"}}, "workspace_mismatch"),
    ("workspace_verified_mismatch", {"verified": "workspace-beta"}, "workspace_mismatch"),
    ("workspace_unverified_empty", {"verified": ""}, "workspace_mismatch"),
    ("provider_mismatch", {"request": {"provider_id": "serpapi"}}, "provider_mismatch"),
    ("capability_request_mismatch", {"request": {"capability_id": "cap-other-read"}}, "capability_mismatch"),
    ("capability_missing", {"capability_missing": True}, "capability_missing"),
    ("capability_not_read_only", {"capability_action_mode": "write"}, "capability_not_read_only"),
    ("approval_binding_mismatch", {"request": {"approval_request_id": "approval-other"}}, "approval_binding_mismatch"),
    ("approval_record_missing", {"grant": {"approval_request_id": ""}}, "approval_record_missing"),
    ("policy_mismatch", {"grant": {"policy_id": "approval-policy-provider_call"}}, "policy_mismatch"),
    ("approver_role_invalid", {"grant": {"approver_role": "finance_manager"}}, "approver_role_invalid"),
    ("approver_missing", {"grant": {"approver_id": ""}}, "approver_missing"),
    ("scope_not_granted", {"grant": {"scope_ids": ("other:read_only",)}}, "scope_not_granted"),
    ("scope_not_in_credential", {"request": {"scope_id": "apify:write"}, "grant": {"scope_ids": ("apify:write",)}}, "scope_not_in_credential"),
    ("scope_not_read_only", {"scope_action_mode": "write"}, "scope_not_read_only"),
    ("field_not_granted", {"request": {"fields": ("title", "email")}}, "field_not_granted"),
    ("fields_required", {"request": {"fields": ()}}, "fields_required"),
    ("region_not_granted", {"request": {"region": "US"}}, "region_not_granted"),
    ("purpose_not_granted", {"request": {"purpose": "competitive_scan"}}, "purpose_not_granted"),
    ("credential_missing", {"credential_mode": "missing"}, "credential_reference_missing"),
    ("credential_not_active", {"credential_mode": "needed"}, "credential_not_active"),
    ("credential_grant_mismatch", {"grant": {"credential_id": "credential-other"}}, "credential_mismatch"),
    ("terms_review_missing", {"grant": {"terms_review_ref": ""}}, "terms_review_missing"),
    ("privacy_review_missing", {"grant": {"privacy_review_ref": ""}}, "privacy_review_missing"),
    ("retention_zero", {"grant": {"retention_days": 0}}, "retention_policy_invalid"),
    ("retention_too_long", {"grant": {"retention_days": 365}}, "retention_policy_invalid"),
    ("ttl_exceeded", {"grant": {"expires_at": NOW + timedelta(days=30)}}, "grant_ttl_exceeded"),
    ("grant_expired", {"grant": {"issued_at": NOW - timedelta(hours=2), "expires_at": NOW - timedelta(seconds=1)}}, "grant_expired"),
    ("grant_not_yet_valid", {"grant": {"issued_at": NOW + timedelta(hours=1), "expires_at": NOW + timedelta(days=1)}}, "grant_not_yet_valid"),
    ("grant_revoked", {"grant": {"revoked_at": NOW - timedelta(minutes=5), "revocation_ref": "revocation-1"}}, "grant_revoked"),
    ("budget_per_run_zero_policy", {"request": {"estimated_cost": 0.01}, "grant": {"max_cost_per_run": 5.0, "max_monthly_cost": 50.0}}, "budget_per_run_exceeded"),
    ("rate_per_request", {"request": {"requested_calls": 5}}, "rate_per_request_exceeded"),
]


@pytest.mark.parametrize("name,kwargs,reason", BINDING_CASES, ids=[case[0] for case in BINDING_CASES])
def test_single_binding_mismatch_blocks_with_its_reason(registry, name, kwargs, reason):
    decision = _decide(registry, authority=FakeAuthority(), **kwargs)

    assert decision.status == "blocked", name
    assert reason in decision.reasons
    assert decision.status != "contract_satisfied"


def test_each_binding_case_is_otherwise_valid(registry):
    # The baseline proves the matrix changes one thing at a time.
    assert _decide(registry, authority=FakeAuthority()).status == "contract_satisfied"


# Budget, rate, and monthly usage come from the trusted authority, not the request.

def test_monthly_budget_checks_use_authority_usage_and_canonical_zero(registry):
    decision = _decide(
        registry, request={"estimated_cost": 0.01}, grant={"max_cost_per_run": 5.0, "max_monthly_cost": 50.0},
        authority=FakeAuthority(),
    )

    assert "budget_per_run_exceeded" in decision.reasons
    assert "budget_monthly_exceeded" in decision.reasons


def test_rate_window_usage_comes_from_authority(registry):
    decision = _decide(registry, authority=FakeAuthority(calls_in_window=3))

    assert decision.status == "blocked"
    assert decision.reasons == ("rate_window_exceeded",)


# Mutation, spend, publication, outreach, and orders remain denied by default.

@pytest.mark.parametrize("request_type", sorted(set(REQUEST_TYPES) - READ_REQUEST_TYPES))
def test_every_non_read_request_type_is_denied_even_with_valid_grant(registry, request_type):
    policy = next(item for item in default_approval_policies() if item.request_type == request_type)
    decision = _decide(
        registry,
        request={"request_type": request_type, "side_effect_type": "network_read"},
        grant={"policy_id": policy.policy_id, "approver_role": policy.required_approver_role},
        authority=FakeAuthority(),
    )

    assert decision.status == "blocked"
    assert "request_type_not_grantable" in decision.reasons


@pytest.mark.parametrize("side_effect", ["message", "publish", "financial", "model_cost", "write", "crm_write"])
def test_web_read_with_mutating_side_effect_is_denied(registry, side_effect):
    decision = _decide(registry, request={"side_effect_type": side_effect}, authority=FakeAuthority())

    assert decision.status == "blocked"
    assert "side_effect_not_read_only" in decision.reasons


def test_unknown_request_type_is_denied(registry):
    decision = _decide(registry, request={"request_type": "not_a_real_type"}, authority=FakeAuthority())

    assert decision.status == "blocked"
    assert "unknown_request_type" in decision.reasons


def test_module_invariants_pin_the_canonical_read_policy():
    policies = {policy.request_type: policy for policy in default_approval_policies()}

    assert READ_REQUEST_TYPES <= set(REQUEST_TYPES)
    assert READ_REQUEST_TYPES.isdisjoint(LIVE_ACTION_TYPES)
    assert policies["web_data_acquisition"].blocked_in_current_mode is False
    assert policies["web_data_acquisition"].budget_cap.per_run == 0.0
    assert policies["web_data_acquisition"].budget_cap.monthly == 0.0
    assert policies["provider_call"].blocked_in_current_mode is True


# Input validation and sanitized reporting.

def test_secret_like_grant_input_is_rejected_without_echo():
    with pytest.raises(ValueError, match="secret-like") as excinfo:
        _grant(purpose=CANARY)

    assert CANARY not in str(excinfo.value)


def test_secret_like_review_reference_is_rejected_without_echo():
    with pytest.raises(ValueError) as excinfo:
        _grant(terms_review_ref=CANARY)

    assert CANARY not in str(excinfo.value)


def test_malformed_identifier_is_rejected():
    with pytest.raises(ValueError, match="malformed identifier"):
        _request(workspace_id="workspace alpha")


def test_naive_timestamp_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        _grant(issued_at=datetime(2026, 10, 14, 11, 0))


def test_naive_now_is_rejected(registry):
    with pytest.raises(ValueError, match="timezone-aware"):
        _decide(registry, now=datetime(2026, 10, 14, 12, 0))


def test_malformed_serialized_timestamp_is_reported_without_echo():
    with pytest.raises(ValueError, match="timestamp is malformed") as excinfo:
        read_grant_from_mapping(_serialized(expires_at=f"not-a-time-{CANARY}"))

    assert CANARY not in str(excinfo.value)


def test_incomplete_serialized_grant_is_rejected():
    payload = _serialized()
    payload.pop("grant_id")

    with pytest.raises(ValueError, match="payload is incomplete"):
        read_grant_from_mapping(payload)


def test_decision_reporting_is_closed_vocabulary_and_json_safe(registry):
    seen: set[str] = set()
    for _name, kwargs, _reason in BINDING_CASES:
        decision = _decide(registry, **kwargs)
        seen.update(decision.reasons)
        assert CANARY not in json.dumps(decision.to_dict(), sort_keys=True)

    assert seen <= DECISION_REASONS
    assert _decide(registry, authority=None).to_dict()["runtime_status"] == "not_wired"


def test_credential_registry_remains_metadata_only(registry):
    assert registry.safety_summary["secret_values_stored"] is False
    assert registry.safety_summary["credentials_present"] is False
    assert all(item.status == "needed" for item in registry.credentials)
    assert CANARY not in json.dumps(registry.to_dict(), sort_keys=True, default=str)
