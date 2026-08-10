from backend.providers.connector_contracts import list_connector_contracts
from backend.providers.vendor_router import recommend_vendor_for_capability


def test_shopify_manual_import_contract_forbids_mutation():
    contract = next(item for item in list_connector_contracts() if item.vendor_id == "shopify" and item.contract_type == "manual_file_read_only_import")
    assert contract.allowed_in_mvp and "create_product" in contract.forbidden_actions
    assert recommend_vendor_for_capability("inventory_monitoring").recommended_vendor_id == "shopify"
