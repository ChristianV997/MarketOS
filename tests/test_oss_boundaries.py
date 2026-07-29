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
        {}, context=SidecarContext(dry_run=False, approval_state="approved")
    )
    assert client.headers["Authorization"] == "Bearer secret"
