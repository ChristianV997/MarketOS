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
    assert result["id"] == "dry-medusa-order-order-1"


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
