"""Tests for backend.contracts.governance."""
import pytest
from backend.contracts.governance.schema_version import SchemaVersion, SCHEMA_VERSIONS
from backend.contracts.governance.compatibility import (
    check_compatibility, assert_compatible, validate_artifact_dict,
)
from backend.contracts.governance.replay_migration import (
    register_migration, migrate, can_migrate,
)
from backend.contracts.governance.registry import GovernanceRegistry, get_governance_registry


# ── SchemaVersion ──────────────────────────────────────────────────────────────

def test_schema_version_parse():
    v = SchemaVersion.parse("1.2.3")
    assert v.major == 1
    assert v.minor == 2
    assert v.patch == 3


def test_schema_version_str():
    assert str(SchemaVersion(1, 2, 3)) == "1.2.3"


def test_schema_version_parse_invalid():
    with pytest.raises(ValueError):
        SchemaVersion.parse("not-a-version")


def test_compatible_same_version():
    v = SchemaVersion(1, 0, 0)
    assert v.is_compatible_with(v)


def test_compatible_older_minor():
    current = SchemaVersion(1, 2, 0)
    older   = SchemaVersion(1, 1, 0)
    assert current.is_compatible_with(older)


def test_incompatible_major_mismatch():
    v1 = SchemaVersion(1, 0, 0)
    v2 = SchemaVersion(2, 0, 0)
    assert not v1.is_compatible_with(v2)


def test_bump_major():
    v = SchemaVersion(1, 3, 2)
    assert v.bump_major() == SchemaVersion(2, 0, 0)


def test_bump_minor():
    v = SchemaVersion(1, 3, 2)
    assert v.bump_minor() == SchemaVersion(1, 4, 0)


def test_to_dict():
    d = SchemaVersion(1, 2, 3).to_dict()
    assert d["major"] == 1
    assert d["str"] == "1.2.3"


# ── Compatibility ──────────────────────────────────────────────────────────────

def test_check_compatible_known_type():
    ok, reason = check_compatibility("campaign", "1.0.0")
    assert ok


def test_check_incompatible_major():
    ok, reason = check_compatibility("campaign", "2.0.0")
    assert not ok


def test_check_unknown_type_passes():
    ok, _ = check_compatibility("totally_new_type", "99.0.0")
    assert ok


def test_assert_compatible_ok():
    assert_compatible("campaign", "1.0.0")


def test_assert_compatible_raises():
    with pytest.raises(ValueError):
        assert_compatible("campaign", "2.0.0")


def test_validate_artifact_dict_valid():
    d = {"artifact_id": "abc", "artifact_type": "campaign", "schema_version": "1.0.0"}
    ok, _ = validate_artifact_dict(d)
    assert ok


def test_validate_artifact_dict_missing_field():
    d = {"artifact_id": "abc", "artifact_type": "campaign"}
    ok, reason = validate_artifact_dict(d)
    assert not ok
    assert "schema_version" in reason


# ── Migration ──────────────────────────────────────────────────────────────────

def test_can_migrate_false_before_register():
    assert not can_migrate("mytype", "0.9.0")


def test_register_and_migrate():
    @register_migration("mytype", "0.9.0")
    def _upgrade(payload):
        payload["schema_version"] = "1.0.0"
        return payload

    assert can_migrate("mytype", "0.9.0")
    result = migrate("mytype", {"schema_version": "0.9.0", "data": "x"})
    assert result["schema_version"] == "1.0.0"


def test_migrate_no_handler_returns_original():
    payload = {"schema_version": "1.0.0", "x": 1}
    result = migrate("no_handler_type", payload)
    assert result is payload


# ── Registry ──────────────────────────────────────────────────────────────────

def test_registry_singleton():
    a = get_governance_registry()
    b = get_governance_registry()
    assert a is b


def test_registry_current_version():
    reg = GovernanceRegistry()
    v = reg.current_version("campaign")
    assert v is not None
    assert v.major == 1


def test_registry_register_custom():
    reg = GovernanceRegistry()
    reg.register("custom_type", SchemaVersion(2, 3, 4))
    v = reg.current_version("custom_type")
    assert v == SchemaVersion(2, 3, 4)


def test_registry_is_compatible():
    reg = GovernanceRegistry()
    assert reg.is_compatible("campaign", "1.0.0")
    assert not reg.is_compatible("campaign", "2.0.0")


def test_registry_all_versions():
    reg = GovernanceRegistry()
    all_v = reg.all_versions()
    assert "campaign" in all_v
    assert isinstance(all_v["campaign"], str)


def test_schema_versions_constant_populated():
    assert len(SCHEMA_VERSIONS) >= 4
