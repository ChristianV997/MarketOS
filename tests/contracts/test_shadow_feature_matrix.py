from backend.evaluation.shadow_features.matrix import CORE_FEATURE_IDS, evaluation_matrix


def test_core_matrix_has_explicit_financial_requirements():
    matrix = evaluation_matrix()
    assert set(CORE_FEATURE_IDS) == set(matrix)
    for feature, requirement in matrix.items():
        assert requirement.minimum_sample_size > 0, feature
        assert requirement.required_event_types, feature
        assert requirement.required_metric_names, feature
        assert requirement.requires_no_live_authority
        assert requirement.requires_no_safety_blockers
