from backend.discovery.source_calibration import CalibrationRun, SourceCalibrationProfile, SourceUsefulnessSignal


def test_models_round_trip_and_cautious_markdown():
    signal = SourceUsefulnessSignal("s", "w", "source", "local_file", "generic_market_csv", signal_type="rank_improvement", entity_name="x", value=1, provenance={"non_causal": True})
    profile = SourceCalibrationProfile("p", "w", "source", "local_file", "generic_market_csv", usefulness_score=999, recommended_priority_adjustment=-999)
    run = CalibrationRun("c", "w", "t", "o", [signal], [profile], "summary", ["next"], "partial")
    assert SourceUsefulnessSignal.from_dict(signal.to_dict()).signal_id == "s"
    assert profile.usefulness_score == 100 and profile.recommended_priority_adjustment == -25
    assert "not causal" in run.to_markdown()
