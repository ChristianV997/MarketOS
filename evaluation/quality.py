"""evaluation.quality — Canonical data-quality authority for MarketOS.

Provides:
1. Core DataQuality reasoning and observation deduplication (`quality_reasons`, `deduplicate_observations`).
2. Declarative Great Expectations-style expectation rules and suites (`ExpectationRule`, `ExpectationSuite`).
3. Deterministic replay certification and fail-closed invariant enforcement (`DeterministicReplayCertifier`, `ReplayCertificationReport`).
4. Direct contract bridges for `DataQuality` records (`certify_data_quality`).
5. Semantic state mappings to TrustOS (`EVIDENCE_STATUSES`) and local quality-gate classes.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping, Optional

from .contracts import CampaignObservation, DataQuality

_SECRET_SHAPED_VALUE = re.compile(
    r"(?is)("
    r"-----begin (?:rsa |ec |dsa |openssh )?private key-----"
    r"|ghp_[A-Za-z0-9_]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|sk-(?:live|test)?-?[A-Za-z0-9]{16,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|bearer [A-Za-z0-9._-]{10,}"
    r")"
)

_FORBIDDEN_RAW_KEYS = frozenset({
    "raw_html", "raw_payload", "raw_body", "raw_response",
    "unredacted_html", "raw_dump", "full_page_html", "cookie_header"
})

CANONICAL_QUALITY_AUTHORITY = "canonical_trustos_quality_gate"
REJECTED_ORCHESTRATORS = frozenset({"temporal", "prefect", "airbyte", "n8n", "celery", "airflow"})


# ---------------------------------------------------------------------------
# Negative Invariant Error Classes
# ---------------------------------------------------------------------------

class InvalidEvidencePromotionError(ValueError):
    """Raised when fixture, mock, or simulated evidence attempts invalid promotion."""


class StaleEvidenceError(ValueError):
    """Raised when stale evidence attempts promotion."""


class AssertionIntegrityError(ValueError):
    """Raised when a failed execution or test is masked as UNAVAILABLE or ignored."""


class UnredactedPayloadError(ValueError):
    """Raised when raw unredacted HTML or payload blobs persist in certified evidence."""


class SecretLeakError(ValueError):
    """Raised when secret-shaped credential tokens are detected in evidence records."""


class DuplicateOrchestratorError(ValueError):
    """Raised when external workflow engines attempt to act as a secondary orchestrator."""


class DuplicateAuthorityError(ValueError):
    """Raised when an external or duplicate quality/lineage authority is introduced."""


# ---------------------------------------------------------------------------
# Quality Assertion States & Declarative Rules
# ---------------------------------------------------------------------------

class QualityAssertionState(str, Enum):
    """Explicit data-quality evaluation state (emulating Great Expectations assertion states)."""
    PASSED = "PASSED"
    FAILED = "FAILED"
    UNAVAILABLE = "UNAVAILABLE"
    DEFERRED = "DEFERRED"


@dataclass(frozen=True)
class QualityAssertionResult:
    """Outcome of a single expectation rule evaluation."""
    rule_id: str
    target_field: str
    state: QualityAssertionState
    observed_value: Any
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "target_field": self.target_field,
            "state": self.state.value,
            "observed_value": str(self.observed_value) if self.observed_value is not None else None,
            "details": self.details,
        }


@dataclass(frozen=True)
class ExpectationRule:
    """Declarative expectation rule."""
    rule_id: str
    description: str
    target_field: str
    assertion_type: str  # exists, bounded_range, allowed_set, non_empty, regex
    params: dict[str, Any] = field(default_factory=dict)

    def evaluate(self, record: Mapping[str, Any]) -> QualityAssertionResult:
        if self.target_field not in record:
            if self.assertion_type == "exists":
                return QualityAssertionResult(self.rule_id, self.target_field, QualityAssertionState.FAILED, None, "Field missing")
            return QualityAssertionResult(self.rule_id, self.target_field, QualityAssertionState.UNAVAILABLE, None, "Field unavailable for evaluation")

        val = record[self.target_field]

        if self.assertion_type == "exists":
            return QualityAssertionResult(self.rule_id, self.target_field, QualityAssertionState.PASSED, val, "Field exists")

        if self.assertion_type == "non_empty":
            if val is None or val == "" or val == [] or val == {}:
                return QualityAssertionResult(self.rule_id, self.target_field, QualityAssertionState.FAILED, val, "Field is empty")
            return QualityAssertionResult(self.rule_id, self.target_field, QualityAssertionState.PASSED, val, "Field is non-empty")

        if self.assertion_type == "bounded_range":
            min_v = self.params.get("min_value")
            max_v = self.params.get("max_value")
            try:
                num = float(val)
            except (ValueError, TypeError):
                return QualityAssertionResult(self.rule_id, self.target_field, QualityAssertionState.FAILED, val, "Non-numeric value for bounded_range")
            if min_v is not None and num < min_v:
                return QualityAssertionResult(self.rule_id, self.target_field, QualityAssertionState.FAILED, val, f"Value {num} below min {min_v}")
            if max_v is not None and num > max_v:
                return QualityAssertionResult(self.rule_id, self.target_field, QualityAssertionState.FAILED, val, f"Value {num} above max {max_v}")
            return QualityAssertionResult(self.rule_id, self.target_field, QualityAssertionState.PASSED, val, "Value within bounds")

        if self.assertion_type == "allowed_set":
            allowed = set(self.params.get("allowed_values", []))
            if val not in allowed:
                return QualityAssertionResult(self.rule_id, self.target_field, QualityAssertionState.FAILED, val, f"Value '{val}' not in allowed set")
            return QualityAssertionResult(self.rule_id, self.target_field, QualityAssertionState.PASSED, val, "Value in allowed set")

        if self.assertion_type == "regex":
            pattern = self.params.get("pattern", "")
            if not re.search(pattern, str(val)):
                return QualityAssertionResult(self.rule_id, self.target_field, QualityAssertionState.FAILED, val, f"Value does not match regex {pattern}")
            return QualityAssertionResult(self.rule_id, self.target_field, QualityAssertionState.PASSED, val, "Regex matched")

        return QualityAssertionResult(self.rule_id, self.target_field, QualityAssertionState.DEFERRED, val, f"Unknown assertion type '{self.assertion_type}'; deferred")


@dataclass(frozen=True)
class ExpectationSuite:
    """A collection of expectation rules evaluated together."""
    suite_id: str
    rules: tuple[ExpectationRule, ...]

    def evaluate_record(self, record: Mapping[str, Any]) -> tuple[QualityAssertionState, list[QualityAssertionResult]]:
        results: list[QualityAssertionResult] = []
        any_failed = False
        any_unavailable = False
        any_deferred = False

        for rule in self.rules:
            res = rule.evaluate(record)
            results.append(res)
            if res.state == QualityAssertionState.FAILED:
                any_failed = True
            elif res.state == QualityAssertionState.UNAVAILABLE:
                any_unavailable = True
            elif res.state == QualityAssertionState.DEFERRED:
                any_deferred = True

        if any_failed:
            overall = QualityAssertionState.FAILED
        elif any_unavailable:
            overall = QualityAssertionState.UNAVAILABLE
        elif any_deferred:
            overall = QualityAssertionState.DEFERRED
        else:
            overall = QualityAssertionState.PASSED

        return overall, results


@dataclass(frozen=True)
class ReplayCertificationReport:
    """Deterministic replay certification output."""
    certification_id: str
    overall_state: QualityAssertionState
    replay_signature: str
    record_fingerprint: str
    assertion_results: tuple[QualityAssertionResult, ...]
    certified_at: str
    authority: str = CANONICAL_QUALITY_AUTHORITY

    def to_dict(self) -> dict[str, Any]:
        return {
            "certification_id": self.certification_id,
            "overall_state": self.overall_state.value,
            "replay_signature": self.replay_signature,
            "record_fingerprint": self.record_fingerprint,
            "assertion_results": [r.to_dict() for r in self.assertion_results],
            "certified_at": self.certified_at,
            "authority": self.authority,
        }


# ---------------------------------------------------------------------------
# Deterministic Replay Certifier
# ---------------------------------------------------------------------------

class DeterministicReplayCertifier:
    """Certifier executing expectation suites and enforcing the 8 negative invariants fail-closed."""

    def __init__(self, authority: str = CANONICAL_QUALITY_AUTHORITY) -> None:
        if authority != CANONICAL_QUALITY_AUTHORITY:
            raise DuplicateAuthorityError(
                f"Invalid quality authority '{authority}': duplicate authority rejected fail-closed"
            )
        self.authority = authority

    def certify(
        self,
        evidence_record: Mapping[str, Any],
        suite: ExpectationSuite,
        *,
        target_provenance: Optional[str] = None,
        max_age_hours: float = 48.0,
        current_time: Optional[datetime] = None,
    ) -> ReplayCertificationReport:
        record_dict = dict(evidence_record)
        serialized = json.dumps(record_dict, default=str)

        # 1. Orchestrator check (negative invariant: external workflow tools cannot become a second orchestrator)
        orchestrator = str(record_dict.get("orchestrator", "")).lower()
        if orchestrator in REJECTED_ORCHESTRATORS or record_dict.get("execution_engine") in REJECTED_ORCHESTRATORS:
            raise DuplicateOrchestratorError(
                f"External orchestrator '{orchestrator or record_dict.get('execution_engine')}' is rejected; MarketOS requires the singular event spine"
            )

        # 2. Secret scan (negative invariant: secrets cannot persist)
        if _SECRET_SHAPED_VALUE.search(serialized):
            raise SecretLeakError("Secret-shaped credential pattern detected in evidence record")

        # 3. Raw payload check (negative invariant: raw payloads cannot persist)
        for forbidden in _FORBIDDEN_RAW_KEYS:
            if forbidden in record_dict:
                raise UnredactedPayloadError(f"Forbidden raw payload field '{forbidden}' found in evidence")
            if f'"{forbidden}"' in serialized:
                raise UnredactedPayloadError(f"Forbidden raw payload key '{forbidden}' found serialized in evidence")

        for k, v in record_dict.items():
            if isinstance(v, str) and (v.strip().startswith("<!DOCTYPE html") or v.strip().startswith("<html")):
                raise UnredactedPayloadError(f"Raw HTML document content detected in field '{k}'")

        # Extract provenance from record or quality sub-object
        quality_obj = record_dict.get("quality")
        if isinstance(quality_obj, dict):
            provenance = quality_obj.get("provenance", "unknown")
            observed_at_raw = quality_obj.get("observed_at")
        else:
            provenance = record_dict.get("provenance", "unknown")
            observed_at_raw = record_dict.get("observed_at")

        # 4. Promotion check: fixture cannot become live evidence
        if target_provenance == "live":
            if provenance in {"mock", "fixture", "synthetic", "fallback", "unknown", "simulated"}:
                raise InvalidEvidencePromotionError(
                    f"Evidence with provenance '{provenance}' cannot be promoted to live evidence"
                )

        # 5. Promotion check: simulated cannot become actual
        if target_provenance == "actual":
            if provenance in {"simulated", "mock", "fixture", "synthetic"}:
                raise InvalidEvidencePromotionError(
                    f"Evidence with provenance '{provenance}' cannot be promoted to actual commercial evidence"
                )

        # 6. Freshness check: stale evidence cannot promote
        now_dt = current_time or datetime.now(timezone.utc)
        if target_provenance in {"promoted", "live", "actual"}:
            if observed_at_raw:
                if isinstance(observed_at_raw, str):
                    try:
                        obs_dt = datetime.fromisoformat(observed_at_raw.replace("Z", "+00:00"))
                    except ValueError:
                        obs_dt = None
                elif isinstance(observed_at_raw, datetime):
                    obs_dt = observed_at_raw
                else:
                    obs_dt = None

                if obs_dt:
                    if obs_dt.tzinfo is None:
                        obs_dt = obs_dt.replace(tzinfo=timezone.utc)
                    age_hours = (now_dt - obs_dt).total_seconds() / 3600.0
                    if age_hours > max_age_hours:
                        raise StaleEvidenceError(
                            f"Evidence age {age_hours:.1f}h exceeds max freshness window of {max_age_hours}h; promotion rejected"
                        )
            else:
                raise StaleEvidenceError("Missing observation timestamp on evidence requested for promotion")

        # 7. Evaluate expectation suite
        overall_state, assertion_results = suite.evaluate_record(record_dict)

        # 8. Check assertion integrity: failed execution cannot become unavailable
        has_failed = any(r.state == QualityAssertionState.FAILED for r in assertion_results)
        if has_failed and overall_state != QualityAssertionState.FAILED:
            raise AssertionIntegrityError("Failed execution or expectation check cannot be masked as UNAVAILABLE")

        # Compute deterministic hashes
        clean_json = json.dumps(record_dict, sort_keys=True, separators=(",", ":"), default=str)
        record_fingerprint = hashlib.sha256(clean_json.encode("utf-8")).hexdigest()

        suite_eval_sig = json.dumps(
            {
                "record_fingerprint": record_fingerprint,
                "suite_id": suite.suite_id,
                "overall_state": overall_state.value,
                "results": [r.to_dict() for r in assertion_results],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        replay_signature = hashlib.sha256(suite_eval_sig.encode("utf-8")).hexdigest()
        cert_id = replay_signature[:16]

        return ReplayCertificationReport(
            certification_id=cert_id,
            overall_state=overall_state,
            replay_signature=replay_signature,
            record_fingerprint=record_fingerprint,
            assertion_results=tuple(assertion_results),
            certified_at=now_dt.isoformat(),
            authority=self.authority,
        )


# ---------------------------------------------------------------------------
# Canonical DataQuality Bridge & Quality Functions
# ---------------------------------------------------------------------------

def quality_reasons(quality: DataQuality, *, max_age_hours: float = 48.0) -> list[str]:
    """Return reasons why a DataQuality record is degraded or unpromoted."""
    reasons: list[str] = []
    if quality.provenance in {"mock", "simulated", "fallback"}:
        reasons.append("synthetic_only")
    if quality.attribution in {"unattributed", "unknown"}:
        reasons.append("unattributed")
    if quality.completeness != "complete":
        reasons.append("incomplete_data")
    age = (datetime.now(timezone.utc) - quality.observed_at).total_seconds() / 3600
    if age > max_age_hours:
        reasons.append("stale_data")
    return reasons


def deduplicate_observations(observations: Iterable[CampaignObservation]) -> list[CampaignObservation]:
    """Deduplicate observations preserving first-seen order."""
    seen: set[str] = set()
    result: list[CampaignObservation] = []
    for observation in observations:
        if observation.observation_id in seen:
            continue
        seen.add(observation.observation_id)
        result.append(observation)
    return result


def certify_data_quality(
    quality: DataQuality,
    *,
    target_provenance: Optional[str] = None,
    max_age_hours: float = 48.0,
    current_time: Optional[datetime] = None,
    certifier: Optional[DeterministicReplayCertifier] = None,
) -> ReplayCertificationReport:
    """Bridge DataQuality contract into deterministic replay certification."""
    active_certifier = certifier or DeterministicReplayCertifier()
    suite = ExpectationSuite(
        suite_id="canonical_data_quality_suite_v1",
        rules=(
            ExpectationRule("rule_completeness", "completeness must be complete", "completeness", "allowed_set", {"allowed_values": ["complete"]}),
            ExpectationRule("rule_provenance", "provenance must be recognized", "provenance", "allowed_set", {"allowed_values": ["live", "simulated", "mock", "fallback", "fixture"]}),
            ExpectationRule("rule_attribution", "attribution must be recognized", "attribution", "allowed_set", {"allowed_values": ["attributed", "unattributed", "unknown"]}),
        ),
    )
    record = {
        "provenance": quality.provenance,
        "attribution": quality.attribution,
        "completeness": quality.completeness,
        "observed_at": quality.observed_at.isoformat(),
        "source_ref": quality.source_ref,
        "retrieval_mode": quality.retrieval_mode,
    }
    return active_certifier.certify(
        record,
        suite,
        target_provenance=target_provenance,
        max_age_hours=max_age_hours,
        current_time=current_time,
    )


# ---------------------------------------------------------------------------
# Quality State Semantic Mappings (TrustOS & Quality Gates)
# ---------------------------------------------------------------------------

def quality_state_to_trustos_evidence_status(state: QualityAssertionState) -> str:
    """Map explicit QualityAssertionState to canonical TrustOS EVIDENCE_STATUSES."""
    mapping = {
        QualityAssertionState.PASSED: "passed",
        QualityAssertionState.FAILED: "failed",
        QualityAssertionState.UNAVAILABLE: "requires_review",
        QualityAssertionState.DEFERRED: "draft",
    }
    return mapping.get(state, "requires_review")


def trustos_evidence_status_to_quality_state(status: str) -> QualityAssertionState:
    """Map TrustOS EVIDENCE_STATUSES to QualityAssertionState."""
    status_lower = status.lower()
    if status_lower in {"passed"}:
        return QualityAssertionState.PASSED
    if status_lower in {"failed"}:
        return QualityAssertionState.FAILED
    if status_lower in {"draft", "not_applicable"}:
        return QualityAssertionState.DEFERRED
    return QualityAssertionState.UNAVAILABLE


def quality_state_to_local_gate_class(state: QualityAssertionState) -> str:
    """Map QualityAssertionState to run_local_quality_gate classification strings."""
    mapping = {
        QualityAssertionState.PASSED: "pass",
        QualityAssertionState.FAILED: "changed_scope_failure",
        QualityAssertionState.UNAVAILABLE: "unavailable_dependency",
        QualityAssertionState.DEFERRED: "not_run",
    }
    return mapping.get(state, "failure_origin_unverified")


__all__ = [
    "CANONICAL_QUALITY_AUTHORITY",
    "REJECTED_ORCHESTRATORS",
    "QualityAssertionState",
    "QualityAssertionResult",
    "ExpectationRule",
    "ExpectationSuite",
    "ReplayCertificationReport",
    "DeterministicReplayCertifier",
    "InvalidEvidencePromotionError",
    "StaleEvidenceError",
    "AssertionIntegrityError",
    "UnredactedPayloadError",
    "SecretLeakError",
    "DuplicateOrchestratorError",
    "DuplicateAuthorityError",
    "quality_reasons",
    "deduplicate_observations",
    "certify_data_quality",
    "quality_state_to_trustos_evidence_status",
    "trustos_evidence_status_to_quality_state",
    "quality_state_to_local_gate_class",
]
