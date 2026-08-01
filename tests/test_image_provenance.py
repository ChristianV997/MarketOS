from scripts.validate_image_provenance import validate_dockerfile


def test_production_image_declares_source_and_revision_provenance():
    assert validate_dockerfile() == []
