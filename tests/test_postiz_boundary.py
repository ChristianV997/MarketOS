from backend.contracts.adapters import SidecarContext
from backend.integrations.postiz import PostizPublisherAdapter


def test_postiz_dry_run_is_network_free():
    result = PostizPublisherAdapter().publish(
        {"text": "hello"}, context=SidecarContext(idempotency_key="abc")
    )
    assert result["id"] == "dry-postiz-abc"
    assert result["dry_run"] is True


def test_postiz_requires_approval_for_live_publish():
    adapter = PostizPublisherAdapter(base_url="https://postiz.invalid", token="token")
    try:
        adapter.publish({"text": "hello"}, context=SidecarContext(dry_run=False, approval_state="pending"))
    except PermissionError:
        pass
    else:
        raise AssertionError("live publishing must require approval")
