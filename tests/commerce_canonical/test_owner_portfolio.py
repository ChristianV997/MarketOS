from evaluation.commerce.owner_portfolio import evaluate_owner_portfolio_gate

def test_missing_report_returns_not_ready():
    result = evaluate_owner_portfolio_gate(None)
    assert result["status"] == "not_ready"
    assert "missing_synthesis_report" in result["reasons"]
    assert result["eligible_candidate_ids"] == []

def test_zero_candidates_returns_not_ready():
    result = evaluate_owner_portfolio_gate({"candidates": []})
    assert result["status"] == "not_ready"
    assert "insufficient_active_candidates: 0 found, 3 required" in result["reasons"]
    assert result["eligible_candidate_ids"] == []

def test_three_distinct_active_candidates_returns_ready():
    report = {
        "candidates": [
            {"candidate_id": "c1"},
            {"candidate_id": "c2"},
            {"candidate_id": "c3"}
        ]
    }
    result = evaluate_owner_portfolio_gate(report)
    assert result["status"] == "ready"
    assert result["reasons"] == []
    assert result["eligible_candidate_ids"] == ["c1", "c2", "c3"]

def test_duplicates_are_collapsed():
    report = {
        "candidates": [
            {"candidate_id": "c1"},
            {"candidate_id": "c2"},
            {"candidate_id": "c2"} # Duplicate
        ]
    }
    result = evaluate_owner_portfolio_gate(report)
    assert result["status"] == "not_ready"
    assert result["eligible_candidate_ids"] == ["c1", "c2"]

def test_malformed_ids_fail_closed():
    report = {
        "candidates": [
            {"candidate_id": "c1"},
            {"candidate_id": ""}, # Empty
            {"candidate_id": None}, # None
            {"candidate_id": "   "}, # Whitespace
            {} # Missing
        ]
    }
    result = evaluate_owner_portfolio_gate(report)
    assert result["status"] == "not_ready"
    assert result["eligible_candidate_ids"] == ["c1"]

def test_archived_candidates_are_excluded():
    report = {
        "candidates": [
            {"candidate_id": "c1"},
            {"candidate_id": "c2"},
            {"candidate_id": "c3", "status": "archived"}
        ]
    }
    result = evaluate_owner_portfolio_gate(report)
    assert result["status"] == "not_ready"
    assert result["eligible_candidate_ids"] == ["c1", "c2"]

def test_ordering_is_stable():
    report = {
        "candidates": [
            {"candidate_id": "z"},
            {"candidate_id": "a"},
            {"candidate_id": "m"}
        ]
    }
    result = evaluate_owner_portfolio_gate(report)
    assert result["status"] == "ready"
    assert result["eligible_candidate_ids"] == ["a", "m", "z"]

def test_does_not_infer_from_score_or_title():
    report = {
        "candidates": [
            # Missing ID but has title/score
            {"title": "Great Product", "score": {"combined_opportunity_score": 0.9}},
            {"candidate_id": "c1"},
            {"candidate_id": "c2"}
        ]
    }
    result = evaluate_owner_portfolio_gate(report)
    assert result["status"] == "not_ready"
    assert result["eligible_candidate_ids"] == ["c1", "c2"]
