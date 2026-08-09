from backend.discovery.connector_stubs import get_connector_stub, list_connector_stubs, validate_connector_stub_disabled


def test_all_stubs_are_disabled_and_non_executable():
    items = list_connector_stubs()
    assert len(items) == 11
    for item in items:
        assert item.default_enabled is False and item.status == "disabled"
        assert not hasattr(item, "run") and not hasattr(item, "fetch")
        assert validate_connector_stub_disabled(item)["allowed"] is False


def test_stub_maps_parser():
    item = get_connector_stub("supplier_catalog_csv")
    assert item.connector_name == "supplier_catalog_export_connector"
