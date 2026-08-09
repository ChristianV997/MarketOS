from backend.discovery.import_templates import create_import_template


def test_template_is_placeholder_and_safe():
    item = create_import_template("supplier_catalog_csv")
    assert item.file_path.endswith("supplier_catalog_csv.csv")
    assert item.example_rows[0]["category"] == "PLACEHOLDER_CATEGORY"
    assert item.metadata["not_real_market_data"] is True


def test_template_path_traversal_rejected():
    import pytest
    with pytest.raises(ValueError): create_import_template("generic_market_csv", "data/import_templates/../outside")
