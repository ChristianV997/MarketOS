"""evaluation/source_governance/registry.py -- Canonical schema and container
for MarketOS source-adaptation records and governance policies.

Ensures that any external public repository or pattern evaluated for adoption
in MarketOS is rigorously registered with immutable revision, license evidence,
inspected paths, security profile, adaptation mode, target authority, attribution,
and rollback strategy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional


class AdaptationMode(str, Enum):
    """Permitted adaptation modes for external sources in MarketOS."""
    INTEGRATE = "integrate"
    EMULATE = "emulate"
    COPY_PATTERN = "copy_pattern"
    REFERENCE_ONLY = "reference_only"
    REJECT = "reject"
    DEFER = "defer"


class SourceType(str, Enum):
    """Categorization of the external source."""
    GIT_REPOSITORY = "git_repository"
    PYTHON_PACKAGE = "python_package"
    NPM_PACKAGE = "npm_package"
    AGENT_FRAMEWORK = "agent_framework"
    SPECIFICATION = "specification"
    META_AGENT_FRAMEWORK = "meta_agent_framework"


class CompatibilityStatus(str, Enum):
    """Compatibility evaluation against MarketOS architecture."""
    COMPATIBLE = "compatible"
    CONDITIONALLY_COMPATIBLE = "conditionally_compatible"
    INCOMPATIBLE_RUNTIME = "incompatible_runtime"
    INCOMPATIBLE_LICENSE = "incompatible_license"
    INCOMPATIBLE_ARCHITECTURE = "incompatible_architecture"
    REJECTED = "rejected"


class IntegrationStatus(str, Enum):
    """Current adoption status in the repository."""
    ACCEPTED = "accepted"
    ACCEPTED_PATTERN = "accepted_pattern"
    EMULATED_IN_TREE = "emulated_in_tree"
    REFERENCE_ONLY = "reference_only"
    DEFERRED = "deferred"
    REJECTED = "rejected"
    CANDIDATE = "candidate"


@dataclass(frozen=True)
class SecuritySurface:
    """Security assessment profile of the external source."""
    network_access: bool = False
    credential_exposure: str = "none"  # "none", "read_only", "write", "high_risk"
    code_execution: bool = False
    local_ipc: bool = False
    desktop_control_risk: bool = False
    attack_surface_notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SecuritySurface:
        return cls(
            network_access=bool(data.get("network_access", False)),
            credential_exposure=str(data.get("credential_exposure", "none")),
            code_execution=bool(data.get("code_execution", False)),
            local_ipc=bool(data.get("local_ipc", False)),
            desktop_control_risk=bool(data.get("desktop_control_risk", False)),
            attack_surface_notes=str(data.get("attack_surface_notes", "")),
        )


@dataclass(frozen=True)
class DataNetworkBehavior:
    """Network and data transmission behavior declaration."""
    network_mode: str = "offline_only"  # "offline_only", "fixture_only", "manual_import", "sandboxed_egress"
    outbound_calls_allowed: bool = False
    telemetry_mode: str = "none"  # "none", "disabled", "opt_in", "simulated"
    data_persistence: str = "none"  # "none", "memory_only", "local_ephemeral", "database"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DataNetworkBehavior:
        return cls(
            network_mode=str(data.get("network_mode", "offline_only")),
            outbound_calls_allowed=bool(data.get("outbound_calls_allowed", False)),
            telemetry_mode=str(data.get("telemetry_mode", "none")),
            data_persistence=str(data.get("data_persistence", "none")),
        )


@dataclass(frozen=True)
class SourceAdaptationRecord:
    """Canonical record representing an evaluated external source or pattern."""
    source_id: str
    repository_url: str
    organization: str
    repository_name: str
    revision: str
    commit_sha: str
    version_tag: str
    source_type: str
    license: str
    license_evidence_url: str
    inspected_paths: tuple[str, ...]
    dependencies: tuple[str, ...]
    security_surface: SecuritySurface
    data_network_behavior: DataNetworkBehavior
    adaptation_mode: str
    marketos_target_authority: str
    expected_benefit: str
    compatibility_status: str
    integration_status: str
    attribution_requirement: str
    rollback_strategy: str
    owner: str
    reviewer: str
    verification_evidence: str
    rejection_reason: Optional[str] = None
    last_reviewed_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "source_id": self.source_id,
            "repository_url": self.repository_url,
            "organization": self.organization,
            "repository_name": self.repository_name,
            "revision": self.revision,
            "commit_sha": self.commit_sha,
            "version_tag": self.version_tag,
            "source_type": self.source_type,
            "license": self.license,
            "license_evidence_url": self.license_evidence_url,
            "inspected_paths": list(self.inspected_paths),
            "dependencies": list(self.dependencies),
            "security_surface": self.security_surface.to_dict(),
            "data_network_behavior": self.data_network_behavior.to_dict(),
            "adaptation_mode": self.adaptation_mode,
            "marketos_target_authority": self.marketos_target_authority,
            "expected_benefit": self.expected_benefit,
            "compatibility_status": self.compatibility_status,
            "integration_status": self.integration_status,
            "attribution_requirement": self.attribution_requirement,
            "rollback_strategy": self.rollback_strategy,
            "owner": self.owner,
            "reviewer": self.reviewer,
            "verification_evidence": self.verification_evidence,
            "rejection_reason": self.rejection_reason,
            "last_reviewed_at": self.last_reviewed_at,
        }
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SourceAdaptationRecord:
        sec_dict = data.get("security_surface", {})
        net_dict = data.get("data_network_behavior", {})
        inspected = data.get("inspected_paths", [])
        deps = data.get("dependencies", [])

        return cls(
            source_id=str(data.get("source_id", "")),
            repository_url=str(data.get("repository_url", "")),
            organization=str(data.get("organization", "")),
            repository_name=str(data.get("repository_name", "")),
            revision=str(data.get("revision", "")),
            commit_sha=str(data.get("commit_sha", "")),
            version_tag=str(data.get("version_tag", "")),
            source_type=str(data.get("source_type", "git_repository")),
            license=str(data.get("license", "")),
            license_evidence_url=str(data.get("license_evidence_url", "")),
            inspected_paths=tuple(str(p) for p in inspected),
            dependencies=tuple(str(d) for d in deps),
            security_surface=SecuritySurface.from_dict(sec_dict) if isinstance(sec_dict, dict) else SecuritySurface(),
            data_network_behavior=DataNetworkBehavior.from_dict(net_dict) if isinstance(net_dict, dict) else DataNetworkBehavior(),
            adaptation_mode=str(data.get("adaptation_mode", AdaptationMode.DEFER.value)),
            marketos_target_authority=str(data.get("marketos_target_authority", "none")),
            expected_benefit=str(data.get("expected_benefit", "")),
            compatibility_status=str(data.get("compatibility_status", CompatibilityStatus.COMPATIBLE.value)),
            integration_status=str(data.get("integration_status", IntegrationStatus.CANDIDATE.value)),
            attribution_requirement=str(data.get("attribution_requirement", "")),
            rollback_strategy=str(data.get("rollback_strategy", "")),
            owner=str(data.get("owner", "")),
            reviewer=str(data.get("reviewer", "")),
            verification_evidence=str(data.get("verification_evidence", "")),
            rejection_reason=data.get("rejection_reason"),
            last_reviewed_at=str(data.get("last_reviewed_at", "")),
        )


_SECRET_SHAPED_RE = re.compile(
    r"(?is)("
    r"-----begin (?:rsa |ec |dsa |openssh )?private key-----"
    r"|ghp_[A-Za-z0-9_]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|sk-(?:live|test)?-?[A-Za-z0-9]{16,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|bearer [A-Za-z0-9._-]{10,}"
    r")"
)


def redact_secrets(val: Any) -> Any:
    """Recursively redacts secret-shaped tokens for display."""
    if isinstance(val, dict):
        return {k: redact_secrets(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [redact_secrets(item) for item in val]
    elif isinstance(val, str):
        if _SECRET_SHAPED_RE.search(val):
            return _SECRET_SHAPED_RE.sub("[REDACTED_SECRET]", val)
        return val
    return val


@dataclass
class SourceAdaptationRegistry:
    """Container managing the full set of evaluated sources."""
    records: Dict[str, SourceAdaptationRecord] = field(default_factory=dict)

    def add_record(self, record: SourceAdaptationRecord) -> None:
        self.records[record.source_id] = record

    def get_record(self, source_id: str) -> Optional[SourceAdaptationRecord]:
        return self.records.get(source_id)

    def to_list(self) -> List[Dict[str, Any]]:
        # Deterministically sort by source_id
        return [self.records[sid].to_dict() for sid in sorted(self.records.keys())]

    def compute_stable_hash(self) -> str:
        """Compute SHA256 content hash of the canonical serialized records."""
        payload = json.dumps(self.to_list(), sort_keys=True, indent=2)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def summarize(self) -> Dict[str, Any]:
        """Produce an aggregate breakdown of sources."""
        modes: Dict[str, int] = {}
        statuses: Dict[str, int] = {}
        licenses: Dict[str, int] = {}
        authorities: Dict[str, int] = {}

        for rec in self.records.values():
            modes[rec.adaptation_mode] = modes.get(rec.adaptation_mode, 0) + 1
            statuses[rec.integration_status] = statuses.get(rec.integration_status, 0) + 1
            licenses[rec.license] = licenses.get(rec.license, 0) + 1
            authorities[rec.marketos_target_authority] = authorities.get(rec.marketos_target_authority, 0) + 1

        return {
            "total_sources": len(self.records),
            "modes": dict(sorted(modes.items())),
            "statuses": dict(sorted(statuses.items())),
            "licenses": dict(sorted(licenses.items())),
            "target_authorities": dict(sorted(authorities.items())),
            "stable_hash": self.compute_stable_hash(),
        }

    @classmethod
    def load_from_file(cls, path: str | Path) -> SourceAdaptationRegistry:
        p = Path(path).resolve()
        if not p.exists():
            raise FileNotFoundError(f"Registry file not found: {p}")
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            raise ValueError("Registry JSON must be an array of source adaptation records")

        registry = cls()
        for item in data:
            rec = SourceAdaptationRecord.from_dict(item)
            registry.add_record(rec)
        return registry

    def save_to_file(self, path: str | Path) -> None:
        p = Path(path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.to_list(), f, indent=2, ensure_ascii=False)
            f.write("\n")
