from backend.commerce.contracts import CreativeArtifact, CreativeBundle
from backend.commerce.loop import CommerceLoop


def test_creative_artifact_serializes_without_fake_file_reference():
    artifact = CreativeArtifact(
        status="generated",
        artifact_id="product-1:signal-1:copy",
        provider="core.creative.generator",
        metadata={"kind": "copy"},
    )

    payload = artifact.to_dict()

    assert payload["status"] == "generated"
    assert payload["provider"] == "core.creative.generator"
    assert payload["content_ref"] is None
    assert payload["dry_run"] is True


def test_creative_artifact_statuses_fail_closed_for_launch():
    assert CreativeArtifact(status="generated").usable_for_launch()
    assert not CreativeArtifact(status="provider_unavailable").usable_for_launch()
    assert not CreativeArtifact(status="generated").usable_for_launch(require_media=True)
    assert CreativeArtifact(status="validated", content_ref="https://cdn.test/ad.mp4").usable_for_launch(require_media=True)


def test_creative_artifact_rejects_unknown_status():
    try:
        CreativeArtifact(status="stub")
    except ValueError as exc:
        assert "unknown creative artifact status" in str(exc)
    else:
        raise AssertionError("unknown status must fail closed")


def test_commerce_quality_gate_marks_unusable_artifact_not_launchable():
    bundle = CreativeBundle(
        artifact_id="bundle-1",
        creative_id="creative-1",
        artifact=CreativeArtifact(status="provider_unavailable"),
    )

    checked, failures = CommerceLoop().quality_gate([bundle])

    assert failures == ["creative-1:artifact_unusable"]
    assert "not_launchable" in checked[0].reasons
