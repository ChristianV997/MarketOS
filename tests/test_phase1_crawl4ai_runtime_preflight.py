from scripts.check_phase1_crawl4ai_runtime import build_report


def test_python_314_without_optional_profile_fails_closed_with_actionable_guidance():
    report = build_report(python_version=(3, 14, 0), modules={})

    assert report["status"] == "blocked"
    assert report["read_only"] is True
    assert report["network_calls"] is False
    assert "python_3_14_optional_profile_not_wheel_ready" in report["blockers"]
    assert "3.12 or 3.13" in report["next_action"]


def test_missing_profile_on_supported_runtime_requires_install_without_false_blocker():
    report = build_report(python_version=(3, 13, 2), modules={})

    assert report["status"] == "install_required"
    assert report["blockers"] == []
    assert report["optional_modules"]["crawl4ai"] is False


def test_complete_optional_runtime_is_ready_for_explicit_browser_probe():
    report = build_report(
        python_version=(3, 13, 2),
        modules={"crawl4ai": True, "lxml": True, "playwright": True},
    )

    assert report["status"] == "ready_for_browser_probe"
    assert report["blockers"] == []
    assert report["read_only"] is True
