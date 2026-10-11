"""Source calibration policy: determinism, attribution, sample size, workspace isolation, and bounded downstream effects.

Every registry is an isolated instance under ``tmp_path`` and every timestamp is explicit, so these tests never
touch shared state or the wall clock.
"""
from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

import backend.discovery.import_recommendation as recommendation_module
import backend.discovery.source_calibration_engine as engine
from backend.discovery import calibration_registry as calibration_module
from backend.discovery.calibration_registry import RUN_RETENTION, CalibrationRegistry
from backend.discovery.category_discovery import CategoryDiscoveryRun
from backend.discovery.discovery_comparison import DiscoveryComparison
from backend.discovery.discovery_registry import DiscoveryRegistry
from backend.discovery.evidence_gap import EvidenceGap, EvidenceGapAnalysis
from backend.discovery.evidence_import import EvidenceImportJob, EvidenceSourceQuality
from backend.discovery.import_recommendation import build_import_recommendation_plan
from backend.discovery.import_registry import EvidenceImportRegistry
from backend.discovery.refinement_registry import RefinementRegistry
from backend.discovery.source_calibration import (
    MAX_ORDERING_EFFECT,
    CalibrationRun,
    STALE_AFTER_SECONDS,
    SourceCalibrationProfile,
    SourceUsefulnessSignal,
    build_source_calibration_profiles,
    wilson_interval,
)
from backend.discovery.source_quality import apply_calibration_to_source_quality

WS = "ws_calibration_a"
OTHER = "ws_calibration_b"
T0 = 1_700_000_000.0
DAY = 24 * 3600
AS_OF = T0 + 10 * DAY


@pytest.fixture
def world(tmp_path, monkeypatch):
    world = SimpleNamespace(
        discovery=DiscoveryRegistry(tmp_path / "discovery.json"),
        imports=EvidenceImportRegistry(tmp_path / "imports.json"),
        refinement=RefinementRegistry(tmp_path / "refinement.json"),
        calibration=CalibrationRegistry(tmp_path / "calibration.json"),
    )
    monkeypatch.setattr(engine, "get_discovery_registry", lambda: world.discovery)
    monkeypatch.setattr(engine, "get_import_registry", lambda: world.imports)
    monkeypatch.setattr(engine, "get_refinement_registry", lambda: world.refinement)
    monkeypatch.setattr(calibration_module, "get_calibration_registry", lambda: world.calibration)
    monkeypatch.setattr(recommendation_module, "get_calibration_registry", lambda: world.calibration)
    return world


def add_discovery(world, discovery_id, sources, *, workspace=WS, created_at=T0):
    world.discovery.register_category_discovery(CategoryDiscoveryRun(discovery_id, workspace, "t", "o", list(sources), "completed", [], 1, [], created_at=created_at, finished_at=created_at))


def add_import(world, import_id, source, *, parser="supplier_catalog_csv", workspace=WS, imported=5, rejected=0, warnings=()):
    world.imports.register_import_job(EvidenceImportJob(import_id=import_id, workspace_id=workspace, source_name=source, source_type="local_file", input_path="x.csv", parser_type=parser, status="completed", records_imported=imported, records_rejected=rejected, warnings=list(warnings), created_at=T0, finished_at=T0))


def add_comparison(world, comparison_id, baseline, current, *, workspace=WS, created_at=T0, movements=None, recs=None, evidence_change=2):
    world.refinement.register_comparison(DiscoveryComparison(
        comparison_id, workspace, baseline, current, "t", "s",
        category_movements=movements if movements is not None else [{"category_name": "c1", "score_change": 5, "rank_change": 1}, {"category_name": "c2", "score_change": 3, "rank_change": 2}],
        evidence_count_change=evidence_change, recommendation_changes=recs or [], created_at=created_at,
    ))


def single_source_comparisons(world, count, *, source="supplier", parser_import=True, created_at=T0, workspace=WS):
    """`count` comparisons, each over one named source with two positive movements."""
    if parser_import:
        add_import(world, f"imp_{source}", source, workspace=workspace)
    for index in range(count):
        add_discovery(world, f"base_{source}_{index}", [source], workspace=workspace, created_at=created_at)
        add_discovery(world, f"cur_{source}_{index}", [source], workspace=workspace, created_at=created_at)
        add_comparison(world, f"cmp_{source}_{index}", f"base_{source}_{index}", f"cur_{source}_{index}", workspace=workspace, created_at=created_at)


def profile_for(run, source="supplier"):
    return next(p for p in run.profiles if p.source_name == source)


# --------------------------------------------------------------------------- determinism


def test_identical_inputs_give_identical_output_regardless_of_comparison_order(world):
    single_source_comparisons(world, 3)
    forward = ["cmp_supplier_0", "cmp_supplier_1", "cmp_supplier_2"]
    first = engine.run_source_calibration(WS, comparison_ids=forward, as_of=AS_OF)
    second = engine.run_source_calibration(WS, comparison_ids=list(reversed(forward)), as_of=AS_OF)
    assert first.to_dict() == second.to_dict()


def test_profile_aggregation_is_permutation_invariant(world):
    single_source_comparisons(world, 3)
    signals = engine.derive_source_usefulness_signals(WS, as_of=AS_OF)
    baseline = [p.to_dict() for p in build_source_calibration_profiles(signals)]
    rng = random.Random(20261011)
    for _ in range(25):
        shuffled = list(signals)
        rng.shuffle(shuffled)
        assert [p.to_dict() for p in build_source_calibration_profiles(shuffled)] == baseline


def test_repeated_runs_overwrite_rather_than_accumulate(world):
    single_source_comparisons(world, 2)
    first = engine.run_source_calibration(WS, as_of=AS_OF)
    signal_count, profile_count = len(world.calibration.signals), len(world.calibration.profiles)
    second = engine.run_source_calibration(WS, as_of=AS_OF)
    assert second.calibration_id == first.calibration_id
    assert len(world.calibration.signals) == signal_count and len(world.calibration.profiles) == profile_count
    assert len(world.calibration.runs) == 1


def test_incomplete_workspace_window_preserves_existing_profiles(world, monkeypatch):
    single_source_comparisons(world, 2)
    engine.run_source_calibration(WS, as_of=AS_OF)
    existing = [profile.to_dict() for profile in world.calibration.list_profiles(WS)]
    assert existing

    monkeypatch.setattr(engine, "COMPARISON_WINDOW", 1)
    incomplete = engine.run_source_calibration(WS, as_of=AS_OF)

    assert incomplete.status == "partial"
    assert incomplete.profiles == []
    assert incomplete.metadata["comparison_window_truncated"] is True
    assert [profile.to_dict() for profile in world.calibration.list_profiles(WS)] == existing
    assert any("existing profiles were preserved" in item for item in incomplete.recommendations)


def test_timestamps_come_from_the_data_not_the_clock(world):
    single_source_comparisons(world, 2, created_at=T0)
    run = engine.run_source_calibration(WS)
    assert run.created_at == T0
    assert profile_for(run).last_updated_at == T0
    assert all(signal.created_at == T0 for signal in run.signals)


# --------------------------------------------------------------------------- attribution and ambiguity


def test_a_multi_source_comparison_cannot_make_any_source_observed(world):
    add_import(world, "imp_a", "alpha"); add_import(world, "imp_b", "beta")
    for index in range(3):
        add_discovery(world, f"base_{index}", [])
        add_discovery(world, f"cur_{index}", ["alpha", "beta"])
        add_comparison(world, f"cmp_{index}", f"base_{index}", f"cur_{index}")
    run = engine.run_source_calibration(WS, as_of=AS_OF)
    assert run.status == "partial" and not [p for p in run.profiles if p.evidence_status == "observed"]
    assert all(s.attribution == "ambiguous_multi_source" and s.exclusion_reason == "ambiguous_multi_source" for s in run.signals if s.comparison_id)
    assert run.metadata["exclusions"]["ambiguous_multi_source"] == 6
    assert all(p.recommended_priority_adjustment == 0.0 and p.confidence_multiplier_adjustment == 1.0 for p in run.profiles)


def test_an_unmatched_source_name_is_excluded_not_guessed(world):
    add_discovery(world, "base", []); add_discovery(world, "cur", ["ghost_source"]); add_comparison(world, "cmp", "base", "cur")
    run = engine.run_source_calibration(WS, as_of=AS_OF)
    assert all(s.parser_type == "unknown" and s.exclusion_reason == "unmatched_import" for s in run.signals if s.comparison_id)
    assert run.metadata["exclusions"] == {"unmatched_import": 1}


def test_two_imports_sharing_a_source_name_are_treated_as_ambiguous(world):
    add_import(world, "imp_one", "supplier"); add_import(world, "imp_two", "supplier")
    single_source_comparisons(world, 2, parser_import=False)
    run = engine.run_source_calibration(WS, as_of=AS_OF)
    assert all(s.exclusion_reason == "ambiguous_import_source" for s in run.signals if s.comparison_id)


def test_a_comparison_with_no_recorded_source_is_unattributed(world):
    add_discovery(world, "base", []); add_discovery(world, "cur", []); add_comparison(world, "cmp", "base", "cur")
    run = engine.run_source_calibration(WS, as_of=AS_OF)
    assert run.signals == [] and run.metadata["exclusions"] == {"source_unattributed": 1}


# --------------------------------------------------------------------------- sample size and confidence


def test_a_single_comparison_is_limited_and_neutral(world):
    single_source_comparisons(world, 1)
    profile = profile_for(engine.run_source_calibration(WS, as_of=AS_OF))
    assert profile.evidence_status == "limited" and profile.comparison_count == 1
    assert profile.recommended_priority_adjustment == 0.0 and profile.confidence_multiplier_adjustment == 1.0


def test_enough_independent_comparisons_become_observed_and_may_adjust(world):
    single_source_comparisons(world, 2)
    run = engine.run_source_calibration(WS, as_of=AS_OF)
    profile = profile_for(run)
    assert profile.evidence_status == "observed" and profile.comparison_count == 2 and profile.eligible_signal_count >= 3
    assert profile.recommended_priority_adjustment > 0 and profile.confidence_multiplier_adjustment > 1.0
    assert run.status == "completed"


def test_positive_share_carries_a_wilson_interval_not_a_point_claim(world):
    single_source_comparisons(world, 2)
    profile = profile_for(engine.run_source_calibration(WS, as_of=AS_OF))
    assert 0.0 <= profile.positive_share_lower_95 < 1.0 and profile.positive_share_lower_95 < profile.positive_share_upper_95 <= 1.0
    assert "optimistic" in profile.provenance["interval_caveat"]


def test_wilson_interval_matches_the_published_worked_example():
    lower, upper = wilson_interval(1, 15)
    assert lower == pytest.approx(0.0120, abs=0.001) and upper == pytest.approx(0.2982, abs=0.001)
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_import_quality_is_counted_once_per_source_not_once_per_comparison(world):
    add_import(world, "imp_supplier", "supplier", rejected=9, imported=2, warnings=["duplicates_removed:4"])
    single_source_comparisons(world, 3, parser_import=False)
    run = engine.run_source_calibration(WS, as_of=AS_OF)
    quality = [s for s in run.signals if s.attribution == "import_quality"]
    assert sorted(s.signal_type for s in quality) == ["duplicate_noise", "unsupported_signal_rejection"]
    assert len(quality) == 2


# --------------------------------------------------------------------------- missing and stale comparisons


def test_a_missing_baseline_is_excluded_and_counted(world):
    add_import(world, "imp_supplier", "supplier"); add_discovery(world, "cur", ["supplier"]); add_comparison(world, "cmp", "never_recorded", "cur")
    run = engine.run_source_calibration(WS, as_of=AS_OF)
    assert run.signals == [] and run.metadata["exclusions"] == {"baseline_missing": 1}


def test_a_stale_comparison_is_excluded_from_the_adjustment(world):
    single_source_comparisons(world, 2, created_at=T0)
    add_discovery(world, "base_fresh", []); add_discovery(world, "cur_fresh", ["supplier"])
    add_comparison(world, "cmp_fresh", "base_fresh", "cur_fresh", created_at=T0 + STALE_AFTER_SECONDS + DAY)
    run = engine.run_source_calibration(WS)
    profile = profile_for(run)
    assert run.metadata["exclusions"]["stale_comparison"] == 2
    assert profile.comparison_count == 1 and profile.evidence_status == "limited"
    assert all(s.exclusion_reason == "stale_comparison" for s in run.signals if s.comparison_id == "cmp_supplier_0")


def test_an_explicit_as_of_can_make_old_comparisons_stale(world):
    single_source_comparisons(world, 2, created_at=T0)
    run = engine.run_source_calibration(WS, as_of=T0 + STALE_AFTER_SECONDS + 1)
    assert run.metadata["exclusions"]["stale_comparison"] == 2 and run.status == "partial"


# --------------------------------------------------------------------------- workspace separation


def test_a_comparison_from_another_workspace_is_not_read(world):
    single_source_comparisons(world, 2, workspace=OTHER)
    run = engine.run_source_calibration(WS, comparison_ids=["cmp_supplier_0", "cmp_supplier_1"], as_of=AS_OF)
    assert run.signals == [] and run.profiles == []


def test_an_import_from_another_workspace_cannot_supply_parser_or_source_metadata(world):
    add_import(world, "foreign_import", "supplier", parser="shopify_orders_csv", workspace=OTHER)
    add_discovery(world, "base", []); add_discovery(world, "cur", ["supplier"]); add_comparison(world, "cmp", "base", "cur")
    run = engine.run_source_calibration(WS, comparison_ids=["cmp"], import_ids=["foreign_import"], as_of=AS_OF)
    assert all(s.parser_type == "unknown" and s.related_import_id == "" for s in run.signals)


def test_a_discovery_from_another_workspace_is_refused(world):
    add_import(world, "imp", "supplier")
    add_discovery(world, "base", [], workspace=WS); add_discovery(world, "cur", ["supplier"], workspace=OTHER)
    add_comparison(world, "cmp", "base", "cur")
    run = engine.run_source_calibration(WS, as_of=AS_OF)
    assert run.signals == [] and run.metadata["exclusions"] == {"cross_workspace_discovery": 1}


def test_profiles_never_resolve_across_workspaces(world):
    single_source_comparisons(world, 2, workspace=OTHER)
    engine.run_source_calibration(OTHER, as_of=AS_OF)
    assert world.calibration.get_profile("supplier", workspace_id=WS) is None
    assert world.calibration.get_profile("supplier") is None
    assert world.calibration.profiles_for_parser(WS, "supplier_catalog_csv") == []


# --------------------------------------------------------------------------- downstream recommendations


def gap(gap_id, *, severity="medium", priority=50.0, parser="supplier_catalog_csv", workspace=WS):
    return EvidenceGap(gap_id, workspace, "category", "x", "x", "margin_proxy", severity, priority, recommended_parser_types=[parser])


def plan_for(*gaps, workspace=WS):
    return build_import_recommendation_plan(EvidenceGapAnalysis("analysis", workspace, "t", "o", list(gaps), created_at=T0))


def observed_profile(*, source="supplier_catalog_csv", adjustment=25.0, workspace=WS, parser="supplier_catalog_csv"):
    return SourceCalibrationProfile("profile_" + source, workspace, source, "local_file", parser, recommended_priority_adjustment=adjustment, evidence_status="observed", comparison_count=2, eligible_signal_count=4, last_updated_at=T0)


def test_an_observed_profile_moves_ordering_only_within_the_policy_bound(world):
    world.calibration.register_profile(observed_profile(adjustment=-25.0))
    recommendation = plan_for(gap("g", priority=50.0)).recommendations[0]
    assert recommendation.priority_score == pytest.approx(50.0 + 5.0 - MAX_ORDERING_EFFECT)
    assert recommendation.metadata["calibration_reason"] == "policy_observed"
    world.calibration.register_profile(observed_profile(adjustment=25.0))
    assert plan_for(gap("g", priority=50.0)).recommendations[0].priority_score == pytest.approx(55.0 + MAX_ORDERING_EFFECT)


def test_calibration_never_orders_a_critical_gap_below_its_floor(world):
    world.calibration.register_profile(observed_profile(adjustment=-25.0))
    recommendation = plan_for(gap("g", severity="critical", priority=30.0)).recommendations[0]
    assert recommendation.priority_score == recommendation_module.CRITICAL_PRIORITY_FLOOR


def test_a_profile_that_is_not_observed_has_no_ordering_effect(world):
    limited = observed_profile(adjustment=25.0)
    limited.evidence_status = "limited"
    world.calibration.register_profile(limited)
    recommendation = plan_for(gap("g", priority=50.0)).recommendations[0]
    assert recommendation.priority_score == pytest.approx(55.0)
    assert recommendation.metadata["calibration_reason"] == "not_observed:limited" and recommendation.metadata["priority_adjustment"] == 0.0


def test_two_sources_for_one_parser_are_not_silently_merged(world):
    world.calibration.register_profile(observed_profile(source="supplier_catalog_csv", adjustment=20.0))
    world.calibration.register_profile(observed_profile(source="supplier_alt", adjustment=-20.0))
    recommendation = plan_for(gap("g", priority=50.0)).recommendations[0]
    assert recommendation.metadata["calibration_reason"] == "ambiguous_profile" and recommendation.priority_score == pytest.approx(55.0)


def test_a_default_source_name_matches_its_parser_so_calibration_applies(world):
    world.calibration.register_profile(observed_profile(source="shopify_orders_csv", adjustment=10.0, parser="shopify_orders_csv"))
    recommendation = plan_for(EvidenceGap("g", WS, "category", "x", "x", "own_store_sales_proxy", "medium", 50.0, recommended_parser_types=["shopify_orders_csv"])).recommendations[0]
    assert recommendation.metadata["calibration_reason"] == "policy_observed"


def test_calibration_never_removes_or_adds_recommendations(world):
    world.calibration.register_profile(observed_profile(adjustment=-25.0))
    gaps = [gap("g1", priority=40.0), gap("g2", priority=60.0, parser="google_trends_csv")]
    assert len(plan_for(*gaps).recommendations) == 2


def test_recommendation_plan_is_identical_across_repeats(world):
    gaps = [gap("g2", priority=60.0, parser="google_trends_csv"), gap("g1", priority=40.0)]
    assert plan_for(*gaps).recommendations[0].to_dict() == plan_for(*gaps).recommendations[0].to_dict()
    assert plan_for(*gaps).to_dict()["plan_id"] == plan_for(*reversed(gaps)).to_dict()["plan_id"]


# --------------------------------------------------------------------------- source quality never inflates


def test_calibration_lowers_confidence_but_never_raises_it_or_changes_safety():
    base = EvidenceSourceQuality("shop", "local_file", 80.0, 0.5, allowed_signal_types=["own_store_sales_proxy"], blocked_signal_types=["profit_proxy"], freshness_label="static", metadata={"synthetic_or_cached_only": False, "parser_type": "supplier_catalog_csv"})
    profile = observed_profile(source="shop", adjustment=0.0)
    profile.confidence_multiplier_adjustment = 1.25
    raised = apply_calibration_to_source_quality(base, profile, as_of=T0)
    assert raised.confidence_multiplier == base.confidence_multiplier
    profile.confidence_multiplier_adjustment = 0.5
    lowered = apply_calibration_to_source_quality(base, profile, as_of=T0)
    assert lowered.confidence_multiplier == pytest.approx(0.25) and lowered.confidence_multiplier < base.confidence_multiplier
    for untouched in ("quality_score", "allowed_signal_types", "blocked_signal_types", "freshness_label", "source_type"):
        assert getattr(lowered, untouched) == getattr(base, untouched)


def test_a_fixture_source_cannot_be_upgraded_to_live_by_calibration():
    fixture = EvidenceSourceQuality("fixture", "fixture", 15.0, 0.15, metadata={"synthetic_or_cached_only": True})
    profile = observed_profile(source="fixture", adjustment=0.0)
    profile.confidence_multiplier_adjustment = 1.25
    adjusted = apply_calibration_to_source_quality(fixture, profile, as_of=T0)
    assert adjusted.source_type == "fixture" and adjusted.freshness_label == "static" and adjusted.confidence_multiplier <= 0.15


def test_an_unobserved_profile_changes_nothing():
    base = EvidenceSourceQuality("shop", "local_file", 80.0, 0.5)
    limited = observed_profile(source="shop", adjustment=0.0)
    limited.evidence_status = "limited"
    limited.confidence_multiplier_adjustment = 0.25
    assert apply_calibration_to_source_quality(base, limited, as_of=T0).confidence_multiplier == 0.5


# --------------------------------------------------------------------------- registry and compatibility


def test_a_reregistered_profile_replaces_the_one_for_its_key(world):
    world.calibration.register_profile(SourceCalibrationProfile("profile_old", WS, "supplier", "local_file", "supplier_catalog_csv"))
    world.calibration.register_profile(SourceCalibrationProfile("profile_new", WS, "supplier", "local_file", "supplier_catalog_csv"))
    assert [p.profile_id for p in world.calibration.profiles_for_parser(WS, "supplier_catalog_csv")] == ["profile_new"]


def test_profiles_saved_before_the_policy_still_load_with_neutral_defaults():
    legacy = {"profile_id": "p", "workspace_id": WS, "source_name": "supplier", "source_type": "local_file", "parser_type": "supplier_catalog_csv", "recommended_priority_adjustment": 9.0}
    profile = SourceCalibrationProfile.from_dict(legacy)
    assert profile.evidence_status == "no_eligible_signals" and profile.recommended_priority_adjustment == 9.0
    assert "evidence_status" in profile.to_dict()


def test_a_signal_that_does_not_state_its_attribution_is_not_eligible():
    signal = SourceUsefulnessSignal("s", WS, "supplier", "local_file", "supplier_catalog_csv", signal_type="rank_improvement", value=2)
    assert not signal.eligible and signal.attribution == "unverified"
    stated = SourceUsefulnessSignal("s", WS, "supplier", "local_file", "supplier_catalog_csv", signal_type="rank_improvement", value=2, attribution="single_source")
    assert stated.eligible


def test_aggregation_is_exact_under_permutation_for_float_hostile_inputs():
    """Many terms of very different magnitude: plain floating-point summation would depend on order here."""
    rng = random.Random(7)
    signals = []
    for index in range(60):
        magnitude = 10 ** rng.uniform(-9, 2)
        signals.append(SourceUsefulnessSignal(
            f"sig{index:03d}", WS, "supplier", "local_file", "supplier_catalog_csv", comparison_id=f"cmp{index % 5}",
            signal_type="confidence_increase" if index % 3 else "low_confidence_noise", value=magnitude,
            confidence=rng.uniform(0.01, 1.0), weight=rng.uniform(0.01, 1.0), created_at=T0,
        ))
    baseline = [p.to_dict() for p in build_source_calibration_profiles(signals)]
    for _ in range(40):
        shuffled = list(signals)
        rng.shuffle(shuffled)
        assert [p.to_dict() for p in build_source_calibration_profiles(shuffled)] == baseline


# --------------------------------------------------------------------------- review findings


def test_a_selection_cannot_hide_a_duplicate_source_name(world):
    add_import(world, "imp_one", "supplier"); add_import(world, "imp_two", "supplier")
    single_source_comparisons(world, 2, parser_import=False)
    run = engine.run_source_calibration(WS, import_ids=["imp_one"], as_of=AS_OF)
    assert all(s.exclusion_reason == "ambiguous_import_source" for s in run.signals if s.comparison_id)
    assert not [p for p in run.profiles if p.evidence_status == "observed"]


def test_a_source_dropped_between_baseline_and_current_is_ambiguous(world):
    add_import(world, "imp_alpha", "alpha")
    for index in range(2):
        add_discovery(world, f"base_{index}", ["alpha", "beta"])
        add_discovery(world, f"cur_{index}", ["alpha"])
        add_comparison(world, f"cmp_{index}", f"base_{index}", f"cur_{index}")
    run = engine.run_source_calibration(WS, as_of=AS_OF)
    assert all(s.exclusion_reason == "ambiguous_multi_source" for s in run.signals if s.comparison_id)
    assert not [p for p in run.profiles if p.evidence_status == "observed"]


def test_import_quality_facts_cannot_make_a_profile_observed(world):
    add_import(world, "imp_supplier", "supplier", rejected=10, imported=2)
    for index in range(2):
        add_discovery(world, f"base_{index}", ["supplier"])
        add_discovery(world, f"cur_{index}", ["supplier"])
        add_comparison(world, f"cmp_{index}", f"base_{index}", f"cur_{index}", movements=[], recs=[], evidence_change=1)
    run = engine.run_source_calibration(WS, as_of=AS_OF)
    profile = profile_for(run)
    assert profile.eligible_signal_count == 2 and profile.evidence_status == "limited"
    assert profile.exclusion_counts.get("import_quality_not_comparison") == 1
    assert profile.recommended_priority_adjustment == 0.0


def test_a_scoped_run_is_recorded_but_does_not_replace_the_workspace_profile(world):
    single_source_comparisons(world, 2)
    engine.run_source_calibration(WS, as_of=AS_OF)
    workspace_profile = world.calibration.get_profile("supplier", workspace_id=WS)
    assert workspace_profile.evidence_status == "observed"
    scoped = engine.run_source_calibration(WS, comparison_ids=["cmp_supplier_0"], as_of=AS_OF)
    assert scoped.metadata["scope"] == "scoped" and profile_for(scoped).evidence_status == "limited"
    assert world.calibration.get_profile("supplier", workspace_id=WS).evidence_status == "observed"
    assert world.calibration.get_calibration_run(scoped.calibration_id) is not None


def test_a_comparison_after_the_reference_time_is_not_read(world):
    single_source_comparisons(world, 2, created_at=T0)
    add_discovery(world, "base_late", ["supplier"]); add_discovery(world, "cur_late", ["supplier"])
    add_comparison(world, "cmp_late", "base_late", "cur_late", created_at=T0 + 5 * DAY)
    run = engine.run_source_calibration(WS, as_of=T0 + DAY)
    assert run.metadata["exclusions"]["after_as_of"] == 1
    assert all(s.comparison_id != "cmp_late" for s in run.signals)
    assert run.created_at == T0 + DAY


def test_a_full_comparison_window_is_reported_as_truncated(world, monkeypatch):
    single_source_comparisons(world, 2)
    real = world.refinement.list_comparisons
    monkeypatch.setattr(world.refinement, "list_comparisons", lambda workspace_id, limit: (real(workspace_id, 500) * 250)[:engine.COMPARISON_WINDOW])
    run = engine.run_source_calibration(WS, as_of=AS_OF)
    assert run.metadata["comparison_window_truncated"] is True
    assert any("most recently registered comparisons" in line for line in run.recommendations)


def test_a_failed_state_write_is_reported_not_claimed_as_completed(world, tmp_path):
    single_source_comparisons(world, 2)
    blocker = tmp_path / "not_a_directory"
    blocker.write_text("x", encoding="utf-8")
    world.calibration.path = blocker / "state.json"  # the parent is a regular file, so every write fails
    run = engine.run_source_calibration(WS, as_of=AS_OF)
    assert run.metadata["persisted"] is False and run.status == "partial"
    assert any("could not be written" in line for line in run.recommendations)


def test_the_persisted_flag_is_stored_with_a_successful_run(world, tmp_path):
    single_source_comparisons(world, 2)
    run = engine.run_source_calibration(WS, as_of=AS_OF)
    assert run.metadata["persisted"] is True
    reloaded = CalibrationRegistry(world.calibration.path)
    assert reloaded.get_calibration_run(run.calibration_id).metadata["persisted"] is True


def test_records_written_before_the_policy_load_as_unverified_and_neutral(tmp_path):
    import json as _json
    path = tmp_path / "legacy.json"
    legacy_signal = {"signal_id": "old", "workspace_id": WS, "source_name": "supplier", "source_type": "local_file", "parser_type": "supplier_catalog_csv", "signal_type": "rank_improvement", "value": 3.0}
    legacy_profile = {"profile_id": "profile_old", "workspace_id": WS, "source_name": "supplier", "source_type": "local_file", "parser_type": "supplier_catalog_csv", "recommended_priority_adjustment": 20.0, "confidence_multiplier_adjustment": 1.25}
    path.write_text(_json.dumps({"signals": {"old": legacy_signal}, "profiles": {"profile_old": legacy_profile}, "runs": {}}), encoding="utf-8")
    registry = CalibrationRegistry(path)
    assert registry.signals["old"].attribution == "legacy_unverified" and not registry.signals["old"].eligible
    loaded = registry.profiles["profile_old"]
    assert loaded.evidence_status == "legacy_unverified" and loaded.recommended_priority_adjustment == 0.0 and loaded.confidence_multiplier_adjustment == 1.0


def test_an_unreadable_registry_is_moved_aside_not_overwritten(tmp_path):
    path = tmp_path / "state.json"
    original = b"{truncated by a crash"
    path.write_bytes(original)
    registry = CalibrationRegistry(path)
    registry.register_profile(SourceCalibrationProfile("p", WS, "supplier", "local_file", "supplier_catalog_csv"))
    assert (tmp_path / "state.json.unreadable-1").read_bytes() == original
    assert CalibrationRegistry(path).get_profile("supplier", workspace_id=WS) is not None


def test_a_neutral_profile_does_not_block_an_observed_one(world):
    world.calibration.register_profile(observed_profile(source="supplier_catalog_csv", adjustment=8.0))
    neutral = SourceCalibrationProfile("profile_alt", WS, "supplier_alt", "local_file", "supplier_catalog_csv")
    world.calibration.register_profile(neutral)
    recommendation = plan_for(gap("g", priority=50.0)).recommendations[0]
    assert recommendation.metadata["calibration_reason"] == "policy_observed"
    assert recommendation.priority_score == pytest.approx(55.0 + 8.0)


def test_a_calibration_failure_during_planning_is_logged(world, monkeypatch, caplog):
    class Broken:
        def profiles_for_parser(self, workspace_id, parser):
            raise RuntimeError("state unreadable")

    monkeypatch.setattr(recommendation_module, "get_calibration_registry", lambda: Broken())
    with caplog.at_level("WARNING"):
        recommendation = plan_for(gap("g", priority=50.0)).recommendations[0]
    assert recommendation.metadata["calibration_reason"] == "calibration_unavailable"
    assert "calibration unavailable" in caplog.text and "state unreadable" not in caplog.text


def test_a_source_name_in_both_baseline_and_current_is_attributed_once(world):
    single_source_comparisons(world, 2)
    signals = engine.derive_source_usefulness_signals(WS, as_of=AS_OF)
    assert {s.attribution for s in signals if s.comparison_id} == {"single_source"}


# --------------------------------------------------------------------------- second review findings


def test_an_observed_profile_ages_out_when_the_plan_is_built_long_after_its_evidence(world):
    world.calibration.register_profile(observed_profile(adjustment=-8.0))
    world.calibration.profiles[next(iter(world.calibration.profiles))].last_updated_at = T0
    stale_plan = build_import_recommendation_plan(EvidenceGapAnalysis("a", WS, "t", "o", [gap("g", priority=50.0)], created_at=T0 + STALE_AFTER_SECONDS + DAY))
    recommendation = stale_plan.recommendations[0]
    assert recommendation.metadata["calibration_reason"] == "stale_profile" and recommendation.priority_score == pytest.approx(55.0)


def test_a_workspace_rerun_retires_a_profile_whose_evidence_has_gone(world):
    single_source_comparisons(world, 2, source="supplier")
    single_source_comparisons(world, 2, source="alpha")
    engine.run_source_calibration(WS, as_of=AS_OF)
    assert world.calibration.get_profile("supplier", workspace_id=WS).evidence_status == "observed"
    for index in range(2):
        world.refinement.comparisons.pop(f"cmp_supplier_{index}")
    engine.run_source_calibration(WS, as_of=AS_OF)
    assert world.calibration.get_profile("supplier", workspace_id=WS) is None
    assert world.calibration.get_profile("alpha", workspace_id=WS).evidence_status == "observed"


def test_a_rerun_with_nothing_in_view_keeps_the_workspace_state(world):
    single_source_comparisons(world, 2)
    engine.run_source_calibration(WS, as_of=AS_OF)
    world.refinement.comparisons.clear()  # for example, the refinement registry was reset
    run = engine.run_source_calibration(WS, as_of=AS_OF)
    assert world.calibration.get_profile("supplier", workspace_id=WS).evidence_status == "observed"
    assert any("were kept" in line for line in run.recommendations)


def test_a_failed_write_leaves_ordering_on_the_previous_profiles(world, tmp_path):
    single_source_comparisons(world, 2)
    engine.run_source_calibration(WS, as_of=AS_OF)
    before = plan_for(gap("g", priority=50.0)).recommendations[0].priority_score
    blocker = tmp_path / "not_a_directory"
    blocker.write_text("x", encoding="utf-8")
    world.calibration.path = blocker / "state.json"
    world.refinement.comparisons.clear()
    run = engine.run_source_calibration(WS, as_of=AS_OF)
    assert run.metadata["persisted"] is False and run.status == "partial"
    assert world.calibration.get_profile("supplier", workspace_id=WS).evidence_status == "observed"
    assert plan_for(gap("g", priority=50.0)).recommendations[0].priority_score == pytest.approx(before)


def test_the_plan_identifier_changes_when_the_calibration_applied_changes(world):
    gaps = [gap("g", priority=50.0)]
    without = plan_for(*gaps).plan_id
    assert plan_for(*gaps).plan_id == without
    world.calibration.register_profile(observed_profile(adjustment=8.0))
    assert plan_for(*gaps).plan_id != without


def test_legacy_profiles_nested_inside_stored_runs_are_neutralised_too(tmp_path):
    import json as _json
    path = tmp_path / "legacy_run.json"
    nested_profile = {"profile_id": "profile_n", "workspace_id": WS, "source_name": "supplier", "source_type": "local_file", "parser_type": "supplier_catalog_csv", "recommended_priority_adjustment": 12.0}
    nested_signal = {"signal_id": "n1", "workspace_id": WS, "source_name": "supplier", "source_type": "local_file", "parser_type": "supplier_catalog_csv", "signal_type": "rank_improvement", "value": 2.0}
    run = {"calibration_id": "calibration_old", "workspace_id": WS, "title": "t", "objective": "o", "signals": [nested_signal], "profiles": [nested_profile]}
    path.write_text(_json.dumps({"signals": {}, "profiles": {}, "runs": {"calibration_old": run}}), encoding="utf-8")
    registry = CalibrationRegistry(path)
    stored = registry.runs["calibration_old"]
    assert stored.profiles[0].evidence_status == "legacy_unverified" and stored.profiles[0].recommended_priority_adjustment == 0.0
    assert stored.signals[0].attribution == "legacy_unverified" and not stored.signals[0].eligible


def test_a_read_error_is_not_treated_as_corruption(tmp_path):
    path = tmp_path / "state.json"
    path.mkdir()  # reading a directory fails with an OSError, which is not evidence that the content is corrupt
    registry = CalibrationRegistry(path)
    assert registry.load_failed is True and path.is_dir()
    registry.register_profile(SourceCalibrationProfile("p", WS, "supplier", "local_file", "supplier_catalog_csv"))
    assert registry.last_save_ok is False and path.is_dir()
    assert not list(tmp_path.glob("state.json.unreadable*"))


def test_a_second_corruption_keeps_the_first_quarantined_copy(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{first", encoding="utf-8")
    CalibrationRegistry(path)
    path.write_text("{second", encoding="utf-8")
    CalibrationRegistry(path)
    assert (tmp_path / "state.json.unreadable-1").read_text(encoding="utf-8") == "{first"
    assert (tmp_path / "state.json.unreadable-2").read_text(encoding="utf-8") == "{second"


def test_import_quality_facts_are_recorded_even_without_comparisons(world):
    add_import(world, "imp_supplier", "supplier", rejected=10, imported=2)
    run = engine.run_source_calibration(WS, as_of=AS_OF)
    facts = [s for s in run.signals if s.attribution == "import_quality"]
    assert [s.signal_type for s in facts] == ["unsupported_signal_rejection"] and not facts[0].eligible
    assert run.metadata["exclusions"]["import_quality_not_comparison"] == 1


# --------------------------------------------------------------------------- third review findings


def test_concurrent_runs_neither_lose_committed_runs_nor_report_false_persistence(tmp_path):
    import sys as _sys
    import threading as _threading
    registry = CalibrationRegistry(tmp_path / "shared.json")
    errors = []

    def writer(worker):
        for index in range(25):
            run = CalibrationRun(f"calibration_{worker}_{index}", WS, "t", "o", [], [], "s", [], "partial", created_at=T0)
            if not registry.record_run([], [], run):
                errors.append((worker, index))

    previous = _sys.getswitchinterval()
    _sys.setswitchinterval(1e-6)  # force frequent thread switches, so an unlocked read-modify-write interleaves
    try:
        threads = [_threading.Thread(target=writer, args=(worker,)) for worker in range(8)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
    finally:
        _sys.setswitchinterval(previous)
    assert errors == [] and len(registry.runs) == RUN_RETENTION
    assert len(CalibrationRegistry(tmp_path / "shared.json").runs) == RUN_RETENTION


def test_invalid_utf8_state_is_quarantined_not_raised(tmp_path):
    path = tmp_path / "state.json"
    path.write_bytes(b"\xff\xfe not json")
    registry = CalibrationRegistry(path)
    assert registry.runs == {} and (tmp_path / "state.json.unreadable-1").exists()
    registry.register_profile(SourceCalibrationProfile("p", WS, "supplier", "local_file", "supplier_catalog_csv"))
    assert CalibrationRegistry(path).get_profile("supplier", workspace_id=WS) is not None


def test_writes_resume_once_an_unreadable_state_becomes_readable(tmp_path):
    path = tmp_path / "state.json"
    path.mkdir()
    registry = CalibrationRegistry(path)
    assert registry.load_failed is True
    path.rmdir()  # the obstruction is gone
    registry.register_profile(SourceCalibrationProfile("p", WS, "supplier", "local_file", "supplier_catalog_csv"))
    assert registry.last_save_ok is True and registry.load_failed is False
    assert CalibrationRegistry(path).get_profile("supplier", workspace_id=WS) is not None


def test_a_workspace_run_retires_the_signals_of_comparisons_that_dropped_out(world):
    single_source_comparisons(world, 2)
    engine.run_source_calibration(WS, as_of=AS_OF)
    before = {s.comparison_id for s in world.calibration.list_signals(workspace_id=WS, limit=1000)}
    assert before == {"cmp_supplier_0", "cmp_supplier_1"}
    world.refinement.comparisons.pop("cmp_supplier_0")
    engine.run_source_calibration(WS, as_of=AS_OF)
    assert {s.comparison_id for s in world.calibration.list_signals(workspace_id=WS, limit=1000)} == {"cmp_supplier_1"}


def test_a_run_that_could_not_be_saved_reports_no_profiles(world, tmp_path):
    single_source_comparisons(world, 2)
    blocker = tmp_path / "not_a_directory"
    blocker.write_text("x", encoding="utf-8")
    world.calibration.path = blocker / "state.json"
    run = engine.run_source_calibration(WS, as_of=AS_OF)
    assert run.metadata["persisted"] is False and run.profiles == []


def test_plans_with_different_priorities_have_different_identifiers(world):
    first = plan_for(gap("same_gap", priority=40.0)).plan_id
    second = plan_for(gap("same_gap", priority=80.0)).plan_id
    assert first != second


def test_a_comparison_window_claim_says_registration_order_not_time(world, monkeypatch):
    single_source_comparisons(world, 2)
    real = world.refinement.list_comparisons
    monkeypatch.setattr(world.refinement, "list_comparisons", lambda workspace_id, limit: (real(workspace_id, 500) * 250)[:engine.COMPARISON_WINDOW])
    run = engine.run_source_calibration(WS, as_of=AS_OF)
    assert any("most recently registered" in line for line in run.recommendations)


# --------------------------------------------------------------------------- fourth review findings


def test_an_unsaved_profile_never_reorders_imports_in_this_process(world, tmp_path):
    blocker = tmp_path / "not_a_directory"
    blocker.write_text("x", encoding="utf-8")
    world.calibration.path = blocker / "state.json"
    world.calibration.register_profile(observed_profile(adjustment=8.0))
    assert world.calibration.last_save_ok is False and world.calibration.profiles == {}
    assert plan_for(gap("g", priority=50.0)).recommendations[0].metadata["calibration_reason"] == "no_profile"


def test_a_profile_dated_after_the_plan_is_not_applied(world):
    future = observed_profile(adjustment=8.0)
    future.last_updated_at = T0 + 30 * DAY
    world.calibration.register_profile(future)
    plan = build_import_recommendation_plan(EvidenceGapAnalysis("a", WS, "t", "o", [gap("g", priority=50.0)], created_at=T0))
    assert plan.recommendations[0].metadata["calibration_reason"] == "profile_after_plan_time"
    assert plan.recommendations[0].priority_score == pytest.approx(55.0)


def test_a_stale_observed_profile_is_reported_as_stale_not_as_ambiguous(world):
    old = observed_profile(adjustment=8.0)
    world.calibration.register_profile(old)
    world.calibration.profiles[old.profile_id].last_updated_at = T0
    neutral = SourceCalibrationProfile("profile_alt", WS, "supplier_alt", "local_file", "supplier_catalog_csv")
    world.calibration.register_profile(neutral)
    plan = build_import_recommendation_plan(EvidenceGapAnalysis("a", WS, "t", "o", [gap("g", priority=50.0)], created_at=T0 + STALE_AFTER_SECONDS + DAY))
    assert plan.recommendations[0].metadata["calibration_reason"] == "stale_profile"


def test_a_scoped_run_does_not_describe_an_ordering_effect(world):
    single_source_comparisons(world, 2)
    scoped = engine.run_source_calibration(WS, comparison_ids=["cmp_supplier_0", "cmp_supplier_1"], as_of=AS_OF)
    assert any(p.evidence_status == "observed" for p in scoped.profiles)
    assert "do not change import ordering" in scoped.summary
    assert not any("may reorder" in line for line in scoped.recommendations)


def test_an_explicit_as_of_replays_the_same_result_after_later_imports_arrive(world):
    single_source_comparisons(world, 2)
    first = engine.run_source_calibration(WS, as_of=T0 + 10 * DAY)
    world.imports.register_import_job(EvidenceImportJob(import_id="imp_late", workspace_id=WS, source_name="supplier", source_type="local_file", input_path="late.csv", parser_type="supplier_catalog_csv", created_at=T0 + 20 * DAY, finished_at=T0 + 20 * DAY))
    replay = engine.run_source_calibration(WS, as_of=T0 + 10 * DAY)
    assert replay.calibration_id == first.calibration_id and replay.to_dict() == first.to_dict()


def test_a_null_category_name_does_not_abort_the_run(world):
    add_import(world, "imp_supplier", "supplier")
    add_discovery(world, "base", ["supplier"]); add_discovery(world, "cur", ["supplier"])
    add_comparison(world, "cmp", "base", "cur", movements=[{"category_name": None, "score_change": 5}, {"category_name": "named", "score_change": 3}])
    run = engine.run_source_calibration(WS, as_of=AS_OF)
    assert {s.entity_name for s in run.signals if s.comparison_id} == {"", "named"}


def test_duplicate_movements_are_counted_and_stored_as_separate_signals(world):
    add_import(world, "imp_supplier", "supplier")
    duplicate = {"category_name": "same", "score_change": 5}
    for index in range(2):
        add_discovery(world, f"base_{index}", ["supplier"]); add_discovery(world, f"cur_{index}", ["supplier"])
        add_comparison(world, f"cmp_{index}", f"base_{index}", f"cur_{index}", movements=[duplicate, dict(duplicate)])
    run = engine.run_source_calibration(WS, as_of=AS_OF)
    confidence = [s for s in run.signals if s.signal_type == "confidence_increase"]
    assert len(confidence) == 4 and len({s.signal_id for s in confidence}) == 4
    assert len([s for s in world.calibration.list_signals(workspace_id=WS, limit=1000) if s.signal_type == "confidence_increase"]) == 4


def test_scoped_runs_over_different_imports_have_different_identifiers(world):
    single_source_comparisons(world, 1)
    first = engine.run_source_calibration(WS, comparison_ids=["cmp_supplier_0"], import_ids=["no_such_a"], as_of=AS_OF)
    second = engine.run_source_calibration(WS, comparison_ids=["cmp_supplier_0"], import_ids=["no_such_b"], as_of=AS_OF)
    assert first.calibration_id != second.calibration_id


def test_source_quality_calibration_without_a_time_has_no_effect():
    base = EvidenceSourceQuality("shop", "local_file", 80.0, 0.5)
    profile = observed_profile(source="shop", adjustment=0.0)
    profile.confidence_multiplier_adjustment = 0.25
    assert apply_calibration_to_source_quality(base, profile).confidence_multiplier == 0.5


def test_readers_never_iterate_over_a_half_written_state(tmp_path):
    import sys as _sys
    import threading as _threading
    registry = CalibrationRegistry(tmp_path / "readers.json")
    failures = []
    stop = _threading.Event()

    def writer():
        generation = 0
        while not stop.is_set() and generation < 80:
            generation += 1
            signals = [SourceUsefulnessSignal(f"g{generation}_{k}", WS, "supplier", "local_file", "supplier_catalog_csv", attribution="single_source", comparison_id=f"c{generation}_{k}", signal_type="rank_improvement", value=1) for k in range(400)]
            run = CalibrationRun(f"calibration_{generation}", WS, "t", "o", [], [], "s", [], "partial", created_at=T0)
            registry.record_run(signals, [observed_profile(adjustment=float(generation % 5))], run, replace_workspace_profiles=True)

    def reader():
        for _ in range(150):
            try:
                registry.list_signals(workspace_id=WS, limit=1000)
                registry.profiles_for_parser(WS, "supplier_catalog_csv")
                registry.list_calibration_runs(WS, 20)
            except RuntimeError as exc:  # "dictionary changed size during iteration" is the failure this guards against
                failures.append(str(exc))

    previous = _sys.getswitchinterval()
    _sys.setswitchinterval(1e-6)
    try:
        threads = [_threading.Thread(target=writer)] + [_threading.Thread(target=reader) for _ in range(3)]
        for thread in threads: thread.start()
        for thread in threads[1:]: thread.join()
        stop.set()
        threads[0].join()
    finally:
        _sys.setswitchinterval(previous)
    assert failures == []


# --------------------------------------------------------------------------- fifth review findings


def test_an_unsaved_run_does_not_describe_ordering_effects(world, tmp_path):
    single_source_comparisons(world, 2)
    blocker = tmp_path / "not_a_directory"
    blocker.write_text("x", encoding="utf-8")
    world.calibration.path = blocker / "state.json"
    run = engine.run_source_calibration(WS, as_of=AS_OF)
    assert "nothing from this run is in use" in run.summary
    assert not any("may reorder" in line or "positive" in line for line in run.recommendations)


def test_repeated_comparison_ids_are_counted_once(world):
    single_source_comparisons(world, 2)
    once = engine.run_source_calibration(WS, comparison_ids=["cmp_supplier_0", "cmp_supplier_1"], as_of=AS_OF)
    repeated = engine.run_source_calibration(WS, comparison_ids=["cmp_supplier_0", "cmp_supplier_0", "cmp_supplier_1"], as_of=AS_OF)
    assert profile_for(repeated).eligible_signal_count == profile_for(once).eligible_signal_count
    assert profile_for(repeated).recommended_priority_adjustment == profile_for(once).recommended_priority_adjustment


def test_unknown_and_foreign_comparison_ids_are_recorded_as_exclusions(world):
    single_source_comparisons(world, 1)
    single_source_comparisons(world, 1, workspace=OTHER, source="other")
    run = engine.run_source_calibration(WS, comparison_ids=["cmp_supplier_0", "typo", "cmp_other_0"], as_of=AS_OF)
    assert run.metadata["exclusions"]["comparison_not_found"] == 1
    assert run.metadata["exclusions"]["cross_workspace_comparison"] == 1


def test_a_full_import_window_is_reported_even_when_as_of_filters_it(world, monkeypatch):
    monkeypatch.setattr(engine, "IMPORT_WINDOW", 3)
    single_source_comparisons(world, 1, parser_import=False)
    add_import(world, "imp_a", "other_a")
    add_import(world, "imp_b", "other_b")
    world.imports.register_import_job(EvidenceImportJob(import_id="imp_late", workspace_id=WS, source_name="supplier", source_type="local_file", input_path="late.csv", parser_type="supplier_catalog_csv", created_at=T0 + 20 * DAY, finished_at=T0 + 20 * DAY))
    run = engine.run_source_calibration(WS, as_of=T0 + 10 * DAY)
    assert run.metadata["import_window_truncated"] is True
    assert any("most recently registered imports" in line for line in run.recommendations)


def test_readers_see_state_that_became_readable_after_a_failed_startup_read(tmp_path):
    path = tmp_path / "state.json"
    path.mkdir()
    reader = CalibrationRegistry(path)
    assert reader.load_failed is True
    path.rmdir()
    CalibrationRegistry(path).register_profile(observed_profile(adjustment=8.0))
    assert reader.profiles_for_parser(WS, "supplier_catalog_csv")[0].evidence_status == "observed"


def test_a_current_profile_applies_beside_a_stale_one_for_the_same_parser(world):
    stale = observed_profile(source="supplier_a", adjustment=-8.0)
    stale.last_updated_at = T0
    current = observed_profile(source="supplier_b", adjustment=8.0)
    current.last_updated_at = T0 + 200 * DAY
    world.calibration.register_profile(stale)
    world.calibration.register_profile(current)
    plan = build_import_recommendation_plan(EvidenceGapAnalysis("a", WS, "t", "o", [gap("g", priority=50.0)], created_at=T0 + 200 * DAY))
    assert plan.recommendations[0].metadata["calibration_reason"] == "policy_observed"
    assert plan.recommendations[0].metadata["calibration_profile_id"] == current.profile_id


def test_a_profile_for_another_source_cannot_lower_this_sources_confidence():
    base = EvidenceSourceQuality("shop", "local_file", 80.0, 0.5, metadata={"parser_type": "supplier_catalog_csv"})
    other = observed_profile(source="other_source", adjustment=0.0)
    other.confidence_multiplier_adjustment = 0.25
    assert apply_calibration_to_source_quality(base, other, as_of=T0).confidence_multiplier == 0.5


def test_run_records_are_capped_and_the_newest_are_kept(tmp_path):
    registry = CalibrationRegistry(tmp_path / "retention.json")
    for index in range(RUN_RETENTION + 5):
        run = CalibrationRun(f"calibration_{index:03d}", WS, "t", "o", [], [], "s", [], "partial", created_at=T0 + index)
        assert registry.record_run([], [], run)
    assert len(registry.runs) == RUN_RETENTION
    assert "calibration_000" not in registry.runs and f"calibration_{RUN_RETENTION + 4:03d}" in registry.runs
