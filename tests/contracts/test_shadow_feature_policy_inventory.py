from backend.evaluation.shadow_features.matrix import CORE_FEATURE_IDS, feature_policies


def test_policy_inventory_maps_core_flags_and_explicitly_defers_noncore_flags():
    policies = feature_policies()
    assert set(CORE_FEATURE_IDS).issubset(policies)
    for feature in CORE_FEATURE_IDS:
        assert policies[feature].status == "implemented"
        assert policies[feature].flag_name
        assert policies[feature].owner_paths
        assert policies[feature].promotion_risk
    deferred = [item for item in policies.values() if item.status == "deferred"]
    assert {item.flag_name for item in deferred} >= {"SUPPLIER_RISK_RANKING_LIVE", "PHASE7_MONTE_CARLO_LIVE", "PHASE8_AFFILIATE_SCALING_LIVE"}
