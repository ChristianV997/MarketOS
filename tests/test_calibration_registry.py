from backend.discovery.calibration_registry import CalibrationRegistry
from backend.discovery.source_calibration import CalibrationRun, SourceCalibrationProfile, SourceUsefulnessSignal


def test_calibration_registry_round_trip(tmp_path):
    registry = CalibrationRegistry(tmp_path / "calibration.json")
    signal = SourceUsefulnessSignal("s", "w", "source", "local_file", "generic_market_csv", signal_type="gap_reduction", provenance={"x": 1})
    profile = SourceCalibrationProfile("p", "w", "source", "local_file", "generic_market_csv")
    run = CalibrationRun("r", "w", "t", "o", [signal], [profile])
    registry.register_signal(signal); registry.register_profile(profile); registry.register_calibration_run(run)
    assert registry.list_signals(workspace_id="w") and registry.get_profile("source", workspace_id="w") and registry.get_calibration_run("r")


def test_corrupt_registry_is_empty(tmp_path):
    path = tmp_path / "bad.json"; path.write_text("{bad", encoding="utf-8")
    registry = CalibrationRegistry(path)
    assert registry.list_signals() == [] and registry.list_profiles() == []
