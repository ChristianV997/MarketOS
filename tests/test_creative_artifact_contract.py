from backend.commerce.contracts import CreativeArtifact


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

