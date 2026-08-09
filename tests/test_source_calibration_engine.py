from types import SimpleNamespace
from backend.discovery.source_calibration import SourceUsefulnessSignal, build_source_calibration_profiles
from backend.discovery.source_calibration_engine import build_source_calibration_profiles as imported_builder, run_source_calibration


def test_no_comparisons_is_partial():
    run = run_source_calibration("calibration-test-no-comparison")
    assert run.status == "partial" and not run.signals


def test_profile_scoring_is_deterministic_and_bounded():
    signals = [SourceUsefulnessSignal(str(i), "w", "source", "local_file", "google_trends_csv", signal_type="rank_improvement", value=2, confidence=1, provenance={"non_causal": True}) for i in range(3)]
    first = build_source_calibration_profiles(signals)[0]; second = imported_builder(signals)[0]
    assert first.to_dict() == second.to_dict() and 0 <= first.usefulness_score <= 100
    negative = SourceUsefulnessSignal("n", "w", "source", "local_file", "google_trends_csv", signal_type="low_confidence_noise", value=1, provenance={})
    assert build_source_calibration_profiles(signals + [negative])[0].weaknesses
