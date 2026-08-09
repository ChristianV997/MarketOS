"""Tests for agents.arbitration — resolving 4 independent AgentDecisions
into one authoritative outcome.

Covers the four design invariants:
  1. veto always wins, regardless of other agents' confidence
  2. orthogonal decisions (geo, audience) both pass through untouched
  3. same-axis conflicts resolve conservatively (halt beats non-halt),
     falling back to confidence only when neither side halts
  4. totality — arbitrate() never raises and always returns one decision,
     even on malformed/empty/all-conflicting input
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from agents.hierarchy import AgentDecision
from agents.arbitration import arbitrate


def _risk(action="hold", confidence=0.5, override=False, reason="ok"):
    return AgentDecision(agent="risk", action=action, confidence=confidence,
                         reason=reason, metadata={"override": override})


def _scaling(action="hold", confidence=0.7, reason="ok"):
    return AgentDecision(agent="scaling", action=action, confidence=confidence,
                         reason=reason)


def _geo(action="test", confidence=0.6, reason="ok"):
    return AgentDecision(agent="geo", action=action, confidence=confidence,
                         reason=reason)


def _audience(action="hold", confidence=0.6, reason="ok"):
    return AgentDecision(agent="audience", action=action, confidence=confidence,
                         reason=reason)


# ─────────────────────────────────────────────────────────────────────────────
# Tier 0: veto
# ─────────────────────────────────────────────────────────────────────────────


class TestVeto:
    def test_kill_switch_overrides_everyone(self):
        decisions = [
            _scaling("scale", confidence=1.0),
            _geo("expand", confidence=1.0),
            _audience("expand", confidence=1.0),
            _risk("kill", confidence=1.0, override=True, reason="kill_switch_activated"),
        ]
        result = arbitrate(decisions)
        assert result.tier == "veto"
        assert result.primary_action == "kill"
        assert result.winning_agents == ["risk"]
        assert "kill_switch_activated" in result.reason

    def test_drawdown_veto_overrides_high_confidence_scale(self):
        decisions = [
            _scaling("scale", confidence=0.99),
            _risk("kill", confidence=0.6, override=True, reason="drawdown=35% > max=30%"),
        ]
        result = arbitrate(decisions)
        assert result.primary_action == "kill"
        assert result.tier == "veto"

    def test_daily_spend_cap_pause_veto(self):
        decisions = [
            _scaling("scale", confidence=1.0),
            _risk("pause", confidence=1.0, override=True, reason="daily_spend_cap"),
        ]
        result = arbitrate(decisions)
        assert result.primary_action == "pause"
        assert result.tier == "veto"

    def test_risk_hold_is_not_a_veto(self):
        decisions = [_scaling("hold"), _risk("hold", override=False)]
        result = arbitrate(decisions)
        assert result.tier == "consensus"

    def test_veto_suppresses_geo_and_audience_axes_from_output(self):
        decisions = [
            _geo("expand", confidence=1.0),
            _audience("expand", confidence=1.0),
            _risk("kill", override=True, reason="emergency"),
        ]
        result = arbitrate(decisions)
        assert result.tier == "veto"
        assert set(result.axis_outcomes.keys()) == {"budget"}


# ─────────────────────────────────────────────────────────────────────────────
# Tier 1: orthogonal axes pass through
# ─────────────────────────────────────────────────────────────────────────────


class TestOrthogonalConsensus:
    def test_geo_and_audience_both_pass_through(self):
        decisions = [
            _scaling("hold"),
            _geo("expand", confidence=0.9),
            _audience("retarget", confidence=0.8),
            _risk("hold", override=False),
        ]
        result = arbitrate(decisions)
        assert result.tier == "consensus"
        assert result.axis_outcomes["geo"].action == "expand"
        assert result.axis_outcomes["geo"].superseded is False
        assert result.axis_outcomes["audience"].action == "retarget"
        assert result.axis_outcomes["audience"].superseded is False

    def test_budget_axis_uses_scaling_when_risk_holds(self):
        decisions = [_scaling("scale", confidence=0.8), _risk("hold")]
        result = arbitrate(decisions)
        assert result.primary_action == "scale"
        assert result.axis_outcomes["budget"].winning_agent == "scaling"

    def test_partial_agent_set_still_resolves(self):
        """Only some agents reported this cycle — still total."""
        result = arbitrate([_geo("expand", confidence=0.9)])
        assert result.tier == "consensus"
        assert result.primary_action == "hold"   # no budget-axis input
        assert result.axis_outcomes["geo"].action == "expand"


# ─────────────────────────────────────────────────────────────────────────────
# Same-axis conflict resolution + budget-axis dominance
# ─────────────────────────────────────────────────────────────────────────────


class TestSameAxisConflict:
    def test_scaling_kill_supersedes_geo_and_audience(self):
        """Gap this closes: scaling says kill, geo/audience still said
        expand/retarget — nothing combined them before. Now budget-axis
        halt supersedes the other axes instead of contradicting itself."""
        decisions = [
            _scaling("kill", confidence=0.95, reason="roas below floor"),
            _geo("expand", confidence=0.9),
            _audience("retarget", confidence=0.8),
            _risk("hold", override=False),
        ]
        result = arbitrate(decisions)
        assert result.primary_action == "kill"
        assert result.axis_outcomes["geo"].superseded is True
        assert result.axis_outcomes["audience"].superseded is True
        assert "budget_axis_halted" in result.axis_outcomes["geo"].superseded_reason

    def test_halting_action_beats_non_halting_on_same_axis(self):
        halt_dec = AgentDecision(agent="risk", action="pause", confidence=0.4,
                                 reason="soft caution", metadata={"override": False})
        scale_dec = _scaling("scale", confidence=0.99)
        result = arbitrate([scale_dec, halt_dec])
        # Even though scaling is far more confident, the halting action wins.
        assert result.axis_outcomes["budget"].action == "pause"
        assert result.unresolved_conflict is False

    def test_confidence_tiebreak_when_neither_side_halts(self):
        decisions = [_scaling("scale", confidence=0.9),
                    _risk("hold", confidence=0.3, override=False)]
        result = arbitrate(decisions)
        assert result.axis_outcomes["budget"].action == "scale"
        assert result.axis_outcomes["budget"].winning_agent == "scaling"

    def test_unanimous_same_axis_no_conflict(self):
        decisions = [_scaling("hold", confidence=0.5),
                    _risk("hold", confidence=0.9, override=False)]
        result = arbitrate(decisions)
        assert result.axis_outcomes["budget"].action == "hold"
        assert "unanimous" in result.axis_outcomes["budget"].reason

    def test_exact_confidence_tie_flags_unresolved(self):
        d1 = AgentDecision(agent="risk", action="hold", confidence=0.5,
                           reason="a", metadata={"override": False})
        d2 = _scaling("scale", confidence=0.5)
        result = arbitrate([d1, d2])
        assert result.axis_outcomes["budget"].action == "hold"
        assert result.unresolved_conflict is True


# ─────────────────────────────────────────────────────────────────────────────
# Totality
# ─────────────────────────────────────────────────────────────────────────────


class TestTotality:
    def test_empty_input_never_raises(self):
        result = arbitrate([])
        assert result.primary_action == "hold"
        assert result.unresolved_conflict is True
        assert result.tier == "fallback"

    def test_none_input_never_raises(self):
        result = arbitrate(None)
        assert result.primary_action == "hold"
        assert result.tier == "fallback"

    def test_malformed_decision_ignored_not_fatal(self):
        result = arbitrate([_scaling("scale"), "not a decision", 42])
        assert result.tier == "consensus"
        assert result.primary_action == "scale"

    def test_all_malformed_falls_back(self):
        result = arbitrate(["nope", None, 3.14])
        assert result.tier == "fallback"
        assert result.primary_action == "hold"

    def test_result_is_always_json_serializable(self):
        import json
        decisions = [_scaling("scale"), _geo("expand"), _audience("retarget"),
                    _risk("hold", override=False)]
        json.dumps(arbitrate(decisions).to_dict())   # must not raise

    def test_agent_with_unmapped_name_gets_own_axis(self):
        """Defensive default: an unknown agent never silently collides
        with an existing axis."""
        weird = AgentDecision(agent="mystery", action="do_something",
                              confidence=0.9, reason="unknown agent")
        result = arbitrate([_scaling("scale"), weird])
        assert "mystery" in result.axis_outcomes
        assert result.axis_outcomes["mystery"].action == "do_something"


# ─────────────────────────────────────────────────────────────────────────────
# Integration: /agents endpoint surfaces the arbitrated outcome
# ─────────────────────────────────────────────────────────────────────────────


class TestAgentsEndpointIntegration:
    def test_agents_endpoint_includes_arbitrated_decision(self):
        from backend.api import app
        client = TestClient(app)
        resp = client.get("/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert "arbitrated_decision" in data
        if data["arbitrated_decision"] is not None:
            ad = data["arbitrated_decision"]
            assert "primary_action" in ad
            assert "tier" in ad
            assert ad["tier"] in {"veto", "consensus", "fallback"}
