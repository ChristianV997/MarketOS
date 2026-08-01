from backend.commerce.contracts import CreativeBundle
from backend.commerce.loop import CommerceLoop


class Publisher:
    def __init__(self):
        self.calls = []
    def publish_bundle(self, bundle, *, context):
        self.calls.append((bundle, context))
        return {"id": "dry-post", "dry_run": context.dry_run, "artifact_id": context.artifact_id}


def test_commerce_loop_publishes_canonical_bundles_with_lineage():
    publisher = Publisher()
    bundle = CreativeBundle(
        artifact_id="bundle-1", parent_ids=["opportunity-1"], workspace="commerce",
        product_id="p1", creative_id="creative-1", primary_text="Try it",
    )
    records = CommerceLoop().publish_creatives([bundle], publisher=publisher)
    assert records == [{"id": "dry-post", "dry_run": True, "artifact_id": "bundle-1"}]
    context = publisher.calls[0][1]
    assert context.parent_ids == ("opportunity-1",)
    assert context.idempotency_key == "publish:creative-1"


def test_commerce_loop_does_not_publish_not_launchable_creatives():
    publisher = Publisher()
    bundle = CreativeBundle(artifact_id="bundle-2", creative_id="c2", reasons=("not_launchable",))
    assert CommerceLoop().publish_creatives([bundle], publisher=publisher) == []
    assert publisher.calls == []
