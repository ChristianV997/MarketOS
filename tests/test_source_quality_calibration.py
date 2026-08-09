from backend.discovery.evidence_import import EvidenceSourceQuality
from backend.discovery.source_calibration import SourceCalibrationProfile
from backend.discovery.source_quality import apply_calibration_to_source_quality


def test_calibration_is_conservative():
    quality = EvidenceSourceQuality("fixture", "fixture", 15, .15, metadata={"synthetic_or_cached_only": True})
    profile = SourceCalibrationProfile("p", "w", "fixture", "fixture", "local_json_dataset", confidence_multiplier_adjustment=1.25)
    adjusted = apply_calibration_to_source_quality(quality, profile)
    assert adjusted.confidence_multiplier <= 1.0


def test_external_source_is_not_upgraded():
    quality = EvidenceSourceQuality("live", "external_live", 0, 0, blocked_signal_types=[])
    profile = SourceCalibrationProfile("p", "w", "live", "external_live", "generic_market_csv", confidence_multiplier_adjustment=1.25)
    assert apply_calibration_to_source_quality(quality, profile).confidence_multiplier == 0
