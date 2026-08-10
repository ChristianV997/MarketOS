from backend.ecommerce.shopify_readonly.models import ShopifyStoreContext


def test_store_context_is_json_safe():
    value = ShopifyStoreContext("w", "b", 1, 2, 3, 4, 5, ("USD",), 1, 0, 12.3, 3.07, ("Product",), (), True)
    assert value.to_dict()["currency_set"] == ["USD"]
