"""backend.contracts.governance — schema versioning and compatibility."""
from .schema_version import SchemaVersion, SCHEMA_VERSIONS
from .compatibility import check_compatibility, assert_compatible, validate_artifact_dict
from .replay_migration import register_migration, migrate, can_migrate
from .registry import GovernanceRegistry, get_governance_registry

__all__ = [
    "SchemaVersion", "SCHEMA_VERSIONS",
    "check_compatibility", "assert_compatible", "validate_artifact_dict",
    "register_migration", "migrate", "can_migrate",
    "GovernanceRegistry", "get_governance_registry",
]
