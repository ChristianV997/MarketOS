from pathlib import Path

from backend.contracts.adapters import SidecarContext
from backend.integrations.medusa import MedusaCommerceAdapter
from scripts.validate_oss_inventory import validate_inventory


ROOT = Path(__file__).parents[1]


def test_oss_inventory_is_valid():
    assert validate_inventory() == []


def test_medusa_is_safe_when_unconfigured():
    adapter = MedusaCommerceAdapter(base_url="")
    health = adapter.health()
    assert health.configured is False
    assert health.reachable is False


def test_medusa_dry_order_never_requires_network():
    adapter = MedusaCommerceAdapter(base_url="")
    result = adapter.create_order(
        {"items": [{"product_id": "p1", "quantity": 1}]},
        context=SidecarContext(idempotency_key="order-1", dry_run=True),
    )
    assert result["dry_run"] is True
    assert result["id"] == "dry-medusa-cart-order-1"
    assert result["cart"]["items"][0]["product_id"] == "p1"


def test_medusa_cart_persists_sidecar_lineage_and_preserves_campaign_metadata():
    result = MedusaCommerceAdapter(base_url="").create_cart(
        {"items": [], "metadata": {"marketos_campaign_id": "campaign-1", "marketos_creative_id": "creative-1"}},
        context=SidecarContext(workspace_id="commerce", run_id="run-1", artifact_id="artifact-1", parent_ids=("signal-1",), idempotency_key="cart-1"),
    )
    metadata = result["cart"]["metadata"]
    assert metadata["marketos_campaign_id"] == "campaign-1"
    assert metadata["marketos_creative_id"] == "creative-1"
    assert metadata["marketos_workspace"] == "commerce"
    assert metadata["marketos_run_id"] == "run-1"
    assert metadata["marketos_artifact_id"] == "artifact-1"
    assert metadata["marketos_parent_ids"] == ["signal-1"]


def test_medusa_dry_checkout_is_explicit_and_network_free():
    result = MedusaCommerceAdapter(base_url="").complete_cart(
        "cart-1", context=SidecarContext(idempotency_key="checkout-1", dry_run=True)
    )
    assert result == {"id": "dry-medusa-order-checkout-1", "dry_run": True, "cart_id": "cart-1"}


def test_medusa_normalizes_sidecar_records_to_canonical_contracts():
    products = MedusaCommerceAdapter.normalize_products([{"id": "p1", "title": "Widget", "price": 12}])
    offers = MedusaCommerceAdapter.normalize_inventory([{"product_id": "p1", "cost": 4, "stocked_quantity": 9}])
    assert products[0].product_id == "p1"
    assert offers[0].product_id == "p1"
    assert offers[0].inventory_units == 9


def test_medusa_maps_variant_prices_and_available_inventory_to_same_candidate_id():
    products = MedusaCommerceAdapter.normalize_products([{
        "id": "prod-1", "title": "Travel Mug", "variants": [{
            "id": "variant-blue", "title": "Blue", "calculated_price": {"calculated_amount": 19.95, "currency_code": "usd"},
        }],
    }])
    offers = MedusaCommerceAdapter.normalize_inventory([{
        "id": "iitem-1", "variants": [{"id": "variant-blue"}],
        "location_levels": [{"stocked_quantity": 10, "reserved_quantity": 3}, {"stocked_quantity": 2, "reserved_quantity": 0}],
    }])
    assert products[0].product_id == offers[0].product_id == "variant-blue"
    assert products[0].name == "Travel Mug — Blue"
    assert products[0].selling_price == 19.95
    assert offers[0].inventory_units == 9


def test_medusa_inventory_fetches_variant_and_level_links_then_filters_locally():
    class Response:
        def raise_for_status(self):
            return None
        def json(self):
            return {"inventory_items": [{"id": "i1", "variants": [{"id": "v1"}]}, {"id": "i2", "variants": [{"id": "v2"}]}]}
    class Client:
        def __init__(self):
            self.calls = []
        def request(self, method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            return Response()

    client = Client()
    rows = MedusaCommerceAdapter(base_url="http://medusa", client=client).get_inventory(("v2",))
    assert rows == [{"id": "i2", "variants": [{"id": "v2"}]}]
    assert client.calls[0][2]["params"] == {"limit": 100, "fields": "*variants,*location_levels"}


def test_medusa_exposes_typed_supplier_offer_boundary():
    class Response:
        def raise_for_status(self):
            return None
        def json(self):
            return {"inventory_items": [{"product_id": "p1", "cost": 4, "stocked_quantity": 9}]}
    class Client:
        def request(self, *_args, **_kwargs):
            return Response()
    offers = MedusaCommerceAdapter(base_url="http://medusa", client=Client()).get_offers(("p1",))
    assert offers[0].product_id == "p1"
    assert offers[0].unit_cost == 4


def test_sidecar_context_carries_lineage_and_approval():
    context = SidecarContext(
        workspace_id="commerce",
        run_id="run-1",
        artifact_id="artifact-1",
        parent_ids=("signal-1",),
        idempotency_key="launch-1",
        dry_run=False,
        approval_state="approved",
    )
    assert context.parent_ids == ("signal-1",)
    assert context.approval_state == "approved"


def test_sidecar_context_builds_canonical_headers():
    context = SidecarContext(workspace_id="w", run_id="r", artifact_id="a", parent_ids=("p1", "p2"), idempotency_key="k", approval_state="approved")
    assert context.to_headers() == {
        "X-MarketOS-Workspace": "w", "X-MarketOS-Run": "r", "X-MarketOS-Artifact": "a",
        "X-MarketOS-Parents": "p1,p2", "X-MarketOS-Approval": "approved", "Idempotency-Key": "k",
    }


def test_medusa_live_order_sends_lineage_and_idempotency_headers():
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"order": {"id": "order-1"}}

    class Client:
        def __init__(self):
            self.calls = []

        def request(self, method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            return Response()

    client = Client()
    adapter = MedusaCommerceAdapter(base_url="http://medusa", client=client)
    context = SidecarContext(
        workspace_id="commerce", run_id="run-1", artifact_id="launch-1",
        idempotency_key="order-key", parent_ids=("candidate-1",), dry_run=False, approval_state="approved",
    )
    result = adapter.create_order({"items": [{"variant_id": "v1", "quantity": 1}]}, context=context)
    assert result["order"]["id"] == "order-1"
    headers = client.calls[0][2]["headers"]
    assert headers["Idempotency-Key"] == "order-key"
    assert headers["X-MarketOS-Workspace"] == "commerce"
    assert headers["X-MarketOS-Run"] == "run-1"
    assert headers["X-MarketOS-Artifact"] == "launch-1"
    assert headers["X-MarketOS-Parents"] == "candidate-1"
    assert headers["X-MarketOS-Approval"] == "approved"
    metadata = client.calls[0][2]["json"]["metadata"]
    assert metadata["marketos_workspace"] == "commerce"
    assert metadata["marketos_run_id"] == "run-1"
    assert metadata["marketos_artifact_id"] == "launch-1"


def test_medusa_live_order_uses_optional_bearer_token():
    class Response:
        def raise_for_status(self):
            return None
        def json(self):
            return {"id": "order-2"}
    class Client:
        def __init__(self):
            self.headers = None
        def request(self, _method, _path, **kwargs):
            self.headers = kwargs["headers"]
            return Response()
    client = Client()
    MedusaCommerceAdapter(base_url="http://medusa", token="secret", client=client).create_order(
        {}, context=SidecarContext(idempotency_key="order-2", dry_run=False, approval_state="approved")
    )
    assert client.headers["Authorization"] == "Bearer secret"


def test_medusa_order_read_uses_admin_route_without_side_effect_context():
    class Response:
        def raise_for_status(self):
            return None
        def json(self):
            return {"order": {"id": "order-1"}}
    class Client:
        def __init__(self):
            self.calls = []
        def request(self, method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            return Response()

    client = Client()
    result = MedusaCommerceAdapter(base_url="http://medusa", client=client).get_order("order-1")
    assert result["order"]["id"] == "order-1"
    assert client.calls == [("GET", "/admin/orders/order-1", {"headers": {}})]


def test_medusa_fulfillment_and_refund_are_dry_run_safe():
    adapter = MedusaCommerceAdapter(base_url="")
    context = SidecarContext(idempotency_key="commerce-action", dry_run=True)
    fulfillment = adapter.fulfill_order(
        "order-1", {"location_id": "sloc-1", "items": [{"id": "item-1", "quantity": 1}]}, context=context,
    )
    refund = adapter.refund_order_payment("order-1", "paycol-1", 19.95, context=context, reason="return")
    assert fulfillment["id"] == "dry-medusa-fulfillment-commerce-action"
    assert refund["refund"] == {"amount": 19.95, "reason": "return"}


def test_medusa_live_fulfillment_and_refund_require_approval_and_idempotency():
    adapter = MedusaCommerceAdapter(base_url="http://medusa")
    try:
        adapter.fulfill_order(
            "order-1", {"location_id": "sloc-1", "items": [{"id": "item-1", "quantity": 1}]},
            context=SidecarContext(dry_run=False, idempotency_key="action-1"),
        )
    except PermissionError as exc:
        assert "approved" in str(exc)
    else:
        raise AssertionError("live fulfillment must require approval")

    try:
        adapter.refund_order_payment(
            "order-1", "paycol-1", 19.95,
            context=SidecarContext(dry_run=False, approval_state="approved"),
        )
    except ValueError as exc:
        assert "idempotency_key" in str(exc)
    else:
        raise AssertionError("live refund must require idempotency")


def test_medusa_live_checkout_requires_explicit_approval_not_implicit_default():
    try:
        MedusaCommerceAdapter(base_url="http://medusa").create_cart(
            {"items": []}, context=SidecarContext(dry_run=False, idempotency_key="cart-1"),
        )
    except PermissionError as exc:
        assert "approved" in str(exc)
    else:
        raise AssertionError("live cart creation must require explicit approval")


def test_medusa_live_fulfillment_and_refund_use_documented_routes_and_headers():
    class Response:
        def raise_for_status(self):
            return None
        def json(self):
            return {"ok": True}
    class Client:
        def __init__(self):
            self.calls = []
        def request(self, method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            return Response()

    client = Client()
    adapter = MedusaCommerceAdapter(base_url="http://medusa", client=client)
    context = SidecarContext(idempotency_key="action-1", dry_run=False, approval_state="approved")
    adapter.fulfill_order("order-1", {"location_id": "sloc-1", "items": [{"id": "item-1", "quantity": 1}]}, context=context)
    adapter.refund_order_payment("order-1", "paycol-1", 19.95, context=context, reason="return")
    assert [call[:2] for call in client.calls] == [
        ("POST", "/admin/orders/order-1/fulfillments"),
        ("POST", "/admin/orders/order-1/payment-collections/paycol-1/refund"),
    ]
    assert client.calls[1][2]["json"] == {"amount": 19.95, "reason": "return"}
    assert client.calls[0][2]["headers"]["Idempotency-Key"] == "action-1"
