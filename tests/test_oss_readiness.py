from scripts.audit_oss_readiness import build_readiness_report


def test_oss_readiness_separates_static_proof_from_external_live_validation():
    report = build_readiness_report()
    assert report["format"] == "marketos-oss-readiness-v1"
    assert report["read_only"] is True
    assert report["static_ready"] is True
    assert "medusa_live_smoke" in report["external_validation"]
    assert "providers" in report["runtime_dry_run"]
