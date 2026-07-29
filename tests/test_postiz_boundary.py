from backend.contracts.adapters import SidecarContext
from backend.integrations.postiz import PostizPublisherAdapter
from backend.commerce.contracts import CreativeBundle


def test_postiz_dry_run_is_network_free():
    result = PostizPublisherAdapter().publish(
        {"text": "hello"}, context=SidecarContext(idempotency_key="abc")
    )
    assert result["id"] == "dry-postiz-abc"
    assert result["dry_run"] is True


def test_postiz_requires_approval_for_live_publish():
    adapter = PostizPublisherAdapter(base_url="https://postiz.invalid/public/v1", token="token", integration_id="integration-1")
    try:
        adapter.publish({"text": "hello"}, context=SidecarContext(dry_run=False, approval_state="pending"))
    except PermissionError:
        pass
    else:
        raise AssertionError("live publishing must require approval")


def test_postiz_live_publish_requires_idempotency_key():
    adapter = PostizPublisherAdapter(base_url="https://postiz.invalid/public/v1", token="token", integration_id="integration-1")
    try:
        adapter.publish({"text": "hello"}, context=SidecarContext(dry_run=False, approval_state="approved"))
    except ValueError as exc:
        assert "idempotency_key" in str(exc)
    else:
        raise AssertionError("live publishing must require idempotency")


def test_postiz_live_publish_requires_explicit_integration_id():
    class Client:
        def post(self, *_args, **_kwargs):
            raise AssertionError("request should not be sent")
    adapter = PostizPublisherAdapter(base_url="https://postiz.invalid/public/v1", token="token", client=Client())
    try:
        adapter.publish({"text": "hello"}, context=SidecarContext(idempotency_key="post-1", dry_run=False, approval_state="approved"))
    except ValueError as exc:
        assert "INTEGRATION_ID" in str(exc)
    else:
        raise AssertionError("live publishing must target an explicit Postiz integration")


def test_postiz_live_publish_sends_lineage_and_idempotency_headers():
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id": "post-1", "status": "published"}

    class Client:
        def __init__(self):
            self.call = None

        def post(self, url, **kwargs):
            self.call = (url, kwargs)
            return Response()

    client = Client()
    adapter = PostizPublisherAdapter(base_url="https://postiz/public/v1", token="secret", integration_id="integration-1", client=client)
    result = adapter.publish(
        {"text": "approved content"},
        context=SidecarContext(
            workspace_id="commerce", run_id="run-2", artifact_id="creative-2",
            idempotency_key="post-key", parent_ids=("bundle-2",), dry_run=False, approval_state="approved",
        ),
    )
    assert result["id"] == "post-1"
    assert client.call[0] == "https://postiz/public/v1/posts"
    headers = client.call[1]["headers"]
    assert headers["Authorization"] == "secret"
    assert headers["Idempotency-Key"] == "post-key"
    assert headers["X-MarketOS-Artifact"] == "creative-2"
    assert headers["X-MarketOS-Parents"] == "bundle-2"
    assert headers["X-MarketOS-Approval"] == "approved"
    assert client.call[1]["json"]["posts"][0]["integration"]["id"] == "integration-1"
    assert client.call[1]["json"]["posts"][0]["settings"]["__type"] == "instagram"


def test_postiz_publish_bundle_maps_canonical_creative_artifact():
    bundle = CreativeBundle(
        artifact_id="bundle-1", product_id="product-1", creative_id="creative-1",
        headline="A useful product", primary_text="Try it today", cta="Shop Now",
        source_refs=("https://source.example/product",),
    )
    result = PostizPublisherAdapter().publish_bundle(bundle, context=SidecarContext(idempotency_key="bundle-1"))
    assert result["dry_run"] is True
    assert result["content"]["artifact_id"] == "bundle-1"
    assert result["content"]["source_refs"] == ["https://source.example/product"]


def test_postiz_retries_transient_transport_failure(monkeypatch):
    class Response:
        status_code = 200
        def raise_for_status(self):
            return None
        def json(self):
            return {"id": "post-retried"}

    class Client:
        def __init__(self):
            self.calls = 0
        def post(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("temporary failure")
            return Response()

    monkeypatch.setenv("POSTIZ_MAX_RETRIES", "1")
    monkeypatch.setenv("POSTIZ_RETRY_BACKOFF_S", "0")
    client = Client()
    result = PostizPublisherAdapter(base_url="https://postiz/public/v1", token="secret", integration_id="integration-1", client=client).publish(
        {"text": "retry me"}, context=SidecarContext(idempotency_key="retry-1", dry_run=False, approval_state="approved")
    )
    assert result["id"] == "post-retried"
    assert client.calls == 2


def test_postiz_fetches_and_normalizes_read_only_analytics():
    class Response:
        def raise_for_status(self):
            return None
        def json(self):
            return [
                {"label": "Impressions", "data": [{"total": "100"}, {"total": "250"}]},
                {"label": "Likes", "data": [{"total": "4"}, {"total": "10"}]},
                {"label": "Comments", "data": [{"total": "1"}, {"total": "3"}]},
                {"label": "Clicks", "data": [{"total": "2"}, {"total": "8"}]},
            ]
    class Client:
        def __init__(self):
            self.call = None
        def get(self, url, **kwargs):
            self.call = (url, kwargs)
            return Response()
    client = Client()
    result = PostizPublisherAdapter(base_url="https://postiz/public/v1", token="secret", client=client).fetch_post_analytics("post-1", days=7)
    assert client.call[0] == "https://postiz/public/v1/analytics/post/post-1"
    assert client.call[1]["params"] == {"date": 7}
    assert result["metrics"] == {"impressions": 250, "clicks": 8, "engagements": 13, "engagement_rate": 0.052}
