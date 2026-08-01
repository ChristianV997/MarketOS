from scripts.validate_license_manifest import validate_manifest


def test_license_manifest_and_notices_match_the_oss_inventory():
    assert validate_manifest() == []
