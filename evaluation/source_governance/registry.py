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
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            json.dump(self.to_list(), f, indent=2, ensure_ascii=False)
            f.write("\n")


@dataclass(frozen=True)
class TargetBoundaryReview:
    """Detailed target boundary audit and collision assessment."""
    target_module: str
    target_symbol: str
    canonical_authority: str
    duplicate_authority_detected: bool
    collision_notes: str
    allowed_symbols: tuple[str, ...]
    prohibited_symbols: tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_module": self.target_module,
            "target_symbol": self.target_symbol,
            "canonical_authority": self.canonical_authority,
            "duplicate_authority_detected": self.duplicate_authority_detected,
            "collision_notes": self.collision_notes,
            "allowed_symbols": list(self.allowed_symbols),
            "prohibited_symbols": list(self.prohibited_symbols),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TargetBoundaryReview:
        return cls(
            target_module=str(data.get("target_module", "")),
            target_symbol=str(data.get("target_symbol", "")),
            canonical_authority=str(data.get("canonical_authority", "none")),
            duplicate_authority_detected=bool(data.get("duplicate_authority_detected", False)),
            collision_notes=str(data.get("collision_notes", "")),
            allowed_symbols=tuple(str(s) for s in data.get("allowed_symbols", [])),
            prohibited_symbols=tuple(str(s) for s in data.get("prohibited_symbols", [])),
        )


@dataclass(frozen=True)
class AdaptationWorkOrder:
    """Canonical executable adaptation work order generated from evaluated source record."""
    work_order_id: str
    source_id: str
    repository_url: str
    commit_sha: str
    version_tag: str
    license: str
    compatibility_status: str
    inspected_paths: tuple[str, ...]
    security_surface: SecuritySurface
    data_network_behavior: DataNetworkBehavior
    adaptation_mode: str
    marketos_target_module: str
    marketos_target_symbol: str
    target_boundary_authority: str
    duplicate_authority_result: str
    required_changes: tuple[str, ...]
    prohibited_changes: tuple[str, ...]
    verification_commands: tuple[str, ...]
    expected_artifacts: tuple[str, ...]
    rollback_deactivation_strategy: str
    attribution_notice: str
    source_freshness_days: int
    review_state: str  # "approved", "rejected", "deferred", "pending_review"
    evidence_classification: str  # "fixture_tested", "dry_run", "integration_tested", "live_validated", "none"
    work_order_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "work_order_id": self.work_order_id,
            "source_id": self.source_id,
            "repository_url": self.repository_url,
            "commit_sha": self.commit_sha,
            "version_tag": self.version_tag,
            "license": self.license,
            "compatibility_status": self.compatibility_status,
            "inspected_paths": list(self.inspected_paths),
            "security_surface": self.security_surface.to_dict(),
            "data_network_behavior": self.data_network_behavior.to_dict(),
            "adaptation_mode": self.adaptation_mode,
            "marketos_target_module": self.marketos_target_module,
            "marketos_target_symbol": self.marketos_target_symbol,
            "target_boundary_authority": self.target_boundary_authority,
            "duplicate_authority_result": self.duplicate_authority_result,
            "required_changes": list(self.required_changes),
            "prohibited_changes": list(self.prohibited_changes),
            "verification_commands": list(self.verification_commands),
            "expected_artifacts": list(self.expected_artifacts),
            "rollback_deactivation_strategy": self.rollback_deactivation_strategy,
            "attribution_notice": self.attribution_notice,
            "source_freshness_days": self.source_freshness_days,
            "review_state": self.review_state,
            "evidence_classification": self.evidence_classification,
            "work_order_hash": self.work_order_hash,
        }

    def compute_hash(self) -> str:
        """Compute SHA256 of the canonical work order without the hash field itself."""
        d = self.to_dict()
        d["work_order_hash"] = ""
        payload = json.dumps(d, sort_keys=True, indent=2)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AdaptationWorkOrder:
        sec_dict = data.get("security_surface", {})
        net_dict = data.get("data_network_behavior", {})

        wo = cls(
            work_order_id=str(data.get("work_order_id", "")),
            source_id=str(data.get("source_id", "")),
            repository_url=str(data.get("repository_url", "")),
            commit_sha=str(data.get("commit_sha", "")),
            version_tag=str(data.get("version_tag", "")),
            license=str(data.get("license", "")),
            compatibility_status=str(data.get("compatibility_status", "compatible")),
            inspected_paths=tuple(str(p) for p in data.get("inspected_paths", [])),
            security_surface=SecuritySurface.from_dict(sec_dict) if isinstance(sec_dict, dict) else SecuritySurface(),
            data_network_behavior=DataNetworkBehavior.from_dict(net_dict) if isinstance(net_dict, dict) else DataNetworkBehavior(),
            adaptation_mode=str(data.get("adaptation_mode", "defer")),
            marketos_target_module=str(data.get("marketos_target_module", "")),
            marketos_target_symbol=str(data.get("marketos_target_symbol", "")),
            target_boundary_authority=str(data.get("target_boundary_authority", "none")),
            duplicate_authority_result=str(data.get("duplicate_authority_result", "passed_no_duplicate")),
            required_changes=tuple(str(c) for c in data.get("required_changes", [])),
            prohibited_changes=tuple(str(c) for c in data.get("prohibited_changes", [])),
            verification_commands=tuple(str(c) for c in data.get("verification_commands", [])),
            expected_artifacts=tuple(str(a) for a in data.get("expected_artifacts", [])),
            rollback_deactivation_strategy=str(data.get("rollback_deactivation_strategy", "")),
            attribution_notice=str(data.get("attribution_notice", "")),
            source_freshness_days=int(data.get("source_freshness_days", 0)),
            review_state=str(data.get("review_state", "pending_review")),
            evidence_classification=str(data.get("evidence_classification", "none")),
            work_order_hash=str(data.get("work_order_hash", "")),
        )
        if not wo.work_order_hash:
            computed = wo.compute_hash()
            return cls(
                work_order_id=wo.work_order_id,
                source_id=wo.source_id,
                repository_url=wo.repository_url,
                commit_sha=wo.commit_sha,
                version_tag=wo.version_tag,
                license=wo.license,
                compatibility_status=wo.compatibility_status,
                inspected_paths=wo.inspected_paths,
                security_surface=wo.security_surface,
                data_network_behavior=wo.data_network_behavior,
                adaptation_mode=wo.adaptation_mode,
                marketos_target_module=wo.marketos_target_module,
                marketos_target_symbol=wo.marketos_target_symbol,
                target_boundary_authority=wo.target_boundary_authority,
                duplicate_authority_result=wo.duplicate_authority_result,
                required_changes=wo.required_changes,
                prohibited_changes=wo.prohibited_changes,
                verification_commands=wo.verification_commands,
                expected_artifacts=wo.expected_artifacts,
                rollback_deactivation_strategy=wo.rollback_deactivation_strategy,
                attribution_notice=wo.attribution_notice,
                source_freshness_days=wo.source_freshness_days,
                review_state=wo.review_state,
                evidence_classification=wo.evidence_classification,
                work_order_hash=computed,
            )
        return wo


@dataclass(frozen=True)
class EvidenceBundle:
    """Reviewer-ready evidence bundle combining source record, work order, and verification proofs."""
    bundle_id: str
    source_id: str
    work_order_id: str
    work_order_hash: str
    adaptation_mode: str
    target_boundary: TargetBoundaryReview
    sanitized_work_order: Dict[str, Any]
    verification_evidence_file: str
    rollback_plan: str
    attribution_notice: str
    safety_certification: Dict[str, bool]
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "source_id": self.source_id,
            "work_order_id": self.work_order_id,
            "work_order_hash": self.work_order_hash,
            "adaptation_mode": self.adaptation_mode,
            "target_boundary": self.target_boundary.to_dict(),
            "sanitized_work_order": redact_secrets(self.sanitized_work_order),
            "verification_evidence_file": self.verification_evidence_file,
            "rollback_plan": self.rollback_plan,
            "attribution_notice": self.attribution_notice,
            "safety_certification": dict(self.safety_certification),
            "created_at": self.created_at,
        }

    def render_markdown(self) -> str:
        lines = [
            f"# Source Adaptation Review Evidence Bundle: {self.source_id}",
            "",
            f"- **Bundle ID**: `{self.bundle_id}`",
            f"- **Work Order ID**: `{self.work_order_id}`",
            f"- **Work Order SHA256**: `{self.work_order_hash}`",
            f"- **Adaptation Mode**: `{self.adaptation_mode}`",
            f"- **Target Module**: `{self.target_boundary.target_module}`",
            f"- **Target Symbol**: `{self.target_boundary.target_symbol}`",
            f"- **Target Authority**: `{self.target_boundary.canonical_authority}`",
            "",
            "## Safety Certification",
            f"- Zero Credentials / No Secret Leaks: `{'PASSED' if self.safety_certification.get('zero_credentials') else 'FAILED'}`",
            f"- Zero Unbounded Network Egress: `{'PASSED' if self.safety_certification.get('zero_network_egress') else 'FAILED'}`",
            f"- Zero Desktop Control / Local IPC Risk: `{'PASSED' if self.safety_certification.get('zero_desktop_control') else 'FAILED'}`",
            f"- Canonical Authority Intact (No Duplication): `{'PASSED' if self.safety_certification.get('canonical_authority_preserved') else 'FAILED'}`",
            f"- Concrete Rollback Plan Specified: `{'PASSED' if self.safety_certification.get('rollback_specified') else 'FAILED'}`",
            "",
            "## Target Boundary Review",
            f"- Collision Notes: {self.target_boundary.collision_notes}",
            f"- Allowed Symbols: {', '.join(self.target_boundary.allowed_symbols) if self.target_boundary.allowed_symbols else 'None'}",
            f"- Prohibited Symbols: {', '.join(self.target_boundary.prohibited_symbols) if self.target_boundary.prohibited_symbols else 'None'}",
            "",
            "## Attribution & Rollback",
            f"- **Attribution Notice**: {self.attribution_notice}",
            f"- **Rollback Strategy**: {self.rollback_plan}",
            f"- **Verification Reference**: `{self.verification_evidence_file}`",
            "",
        ]
        return "\n".join(lines)


def generate_work_order_from_source_record(
    record: SourceAdaptationRecord,
    freshness_days: int = 0,
) -> AdaptationWorkOrder:
    """Construct an executable AdaptationWorkOrder from a validated SourceAdaptationRecord."""
    wo_id = f"wo-{record.source_id.replace('src-', '')}"
    target_mod = ""
    target_sym = ""
    target_auth = record.marketos_target_authority

    # Derive target module and symbol from target_authority if applicable
    if target_auth and target_auth not in ("none", "n/a"):
        parts = target_auth.split(".")
        if len(parts) > 1:
            target_mod = "/".join(parts[:-1]) + ".py"
            target_sym = parts[-1]
        else:
            target_mod = target_auth
            target_sym = "main"

    # Specific symbol disambiguation for multi-source emulations
    if record.source_id == "src-openlineage":
        target_mod = "backend/observability/lineage_facets.py"
        target_sym = "EvidenceLineageFacet"
    elif record.source_id == "src-dagster":
        target_mod = "backend/observability/lineage_facets.py"
        target_sym = "AssetFacet"
    elif record.source_id == "src-great-expectations":
        target_mod = "evaluation/quality.py"
        target_sym = "evaluate_quality"
    elif record.source_id == "src-crawl4ai":
        target_mod = "backend/adapters/research/crawl4ai.py"
        target_sym = "Crawl4AIResearchAdapter"
    elif record.source_id == "src-pyperf":
        target_mod = "scripts/benchmarks/perf_engine.py"
        target_sym = "run_benchmark"

    req_changes: List[str] = []

    proh_changes: List[str] = [
        "do_not_enable_live_credentials",
        "do_not_introduce_desktop_control_ipc",
        "do_not_duplicate_event_spine_or_trustos",
        "do_not_introduce_unapproved_runtimes",
    ]
    verif_cmds: List[str] = [
        "pytest tests/contracts/test_source_adaptation_governance.py",
        "git diff --check",
    ]
    exp_artifacts: List[str] = []

    if record.adaptation_mode == AdaptationMode.COPY_PATTERN.value:
        req_changes.append(f"Adapt pattern from {record.source_id} into in-tree module")
        req_changes.append(f"Add attribution entry in THIRD_PARTY_NOTICES.md")
        exp_artifacts.append(target_mod if target_mod else f"docs/ai/{record.source_id}.md")
    elif record.adaptation_mode == AdaptationMode.EMULATE.value:
        req_changes.append(f"Emulate contract interface without vendoring external code")
        exp_artifacts.append(target_mod if target_mod else f"docs/ai/{record.source_id}.md")
    elif record.adaptation_mode == AdaptationMode.REFERENCE_ONLY.value:
        req_changes.append(f"Document design pattern in docs/ai/ for operator guidance only")
        exp_artifacts.append(f"docs/ai/{record.source_id}_reference.md")
    elif record.adaptation_mode == AdaptationMode.REJECT.value:
        req_changes.append(f"Enforce negative regression test blocking {record.source_id}")
        proh_changes.append(f"do_not_vendor_{record.source_id}")
    elif record.adaptation_mode == AdaptationMode.DEFER.value:
        if record.source_id == "src-crawl4ai":
            req_changes.append(
                "Verify the immutable upstream commit and version tag against authoritative sources before enabling an active mode"
            )
        else:
            req_changes.append("Maintain deferred status until required infrastructure is approved")

    # Review state determination
    if record.adaptation_mode in (AdaptationMode.COPY_PATTERN.value, AdaptationMode.EMULATE.value):
        rev_state = "approved" if record.integration_status in (IntegrationStatus.ACCEPTED_PATTERN.value, IntegrationStatus.ACCEPTED.value, IntegrationStatus.EMULATED_IN_TREE.value) else "pending_review"
        evid_class = "fixture_tested"
    elif record.adaptation_mode == AdaptationMode.REFERENCE_ONLY.value:
        rev_state = "approved"
        evid_class = "dry_run"
    elif record.adaptation_mode == AdaptationMode.REJECT.value:
        rev_state = "rejected"
        evid_class = "none"
    else:
        rev_state = "deferred"
        evid_class = "none"

    wo = AdaptationWorkOrder(
        work_order_id=wo_id,
        source_id=record.source_id,
        repository_url=record.repository_url,
        commit_sha=record.commit_sha,
        version_tag=record.version_tag,
        license=record.license,
        compatibility_status=record.compatibility_status,
        inspected_paths=record.inspected_paths,
        security_surface=record.security_surface,
        data_network_behavior=record.data_network_behavior,
        adaptation_mode=record.adaptation_mode,
        marketos_target_module=target_mod,
        marketos_target_symbol=target_sym,
        target_boundary_authority=target_auth,
        duplicate_authority_result="passed_no_duplicate",
        required_changes=tuple(req_changes),
        prohibited_changes=tuple(proh_changes),
        verification_commands=tuple(verif_cmds),
        expected_artifacts=tuple(exp_artifacts),
        rollback_deactivation_strategy=record.rollback_strategy,
        attribution_notice=record.attribution_requirement,
        source_freshness_days=freshness_days,
        review_state=rev_state,
        evidence_classification=evid_class,
    )
    computed = wo.compute_hash()
    return AdaptationWorkOrder.from_dict({**wo.to_dict(), "work_order_hash": computed})


@dataclass
class WorkOrderRegistry:
    """Container managing the full set of generated adaptation work orders."""
    work_orders: Dict[str, AdaptationWorkOrder] = field(default_factory=dict)

    def add_work_order(self, wo: AdaptationWorkOrder) -> None:
        self.work_orders[wo.work_order_id] = wo

    def get_work_order(self, wo_id: str) -> Optional[AdaptationWorkOrder]:
        return self.work_orders.get(wo_id)

    def to_list(self) -> List[Dict[str, Any]]:
        return [self.work_orders[wid].to_dict() for wid in sorted(self.work_orders.keys())]

    def compute_stable_hash(self) -> str:
        payload = json.dumps(self.to_list(), sort_keys=True, indent=2)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def load_from_file(cls, path: str | Path) -> WorkOrderRegistry:
        p = Path(path).resolve()
        if not p.exists():
            raise FileNotFoundError(f"Work order registry file not found: {p}")
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("Work order registry JSON must be an array of work orders")
        registry = cls()
        for item in data:
            registry.add_work_order(AdaptationWorkOrder.from_dict(item))
        return registry

    def save_to_file(self, path: str | Path) -> None:
        p = Path(path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            json.dump(self.to_list(), f, indent=2, ensure_ascii=False)
            f.write("\n")
