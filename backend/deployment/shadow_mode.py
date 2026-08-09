"""Shadow-mode deployment: run Phase 7-8 logic in parallel without affecting live decisions.

Both old (baseline) and new (Phase 7-8) logic compute decisions and metrics.
Old path controls behavior; new path is journaled for validation.

Validation gates before flipping flag to new path:
1. New path accuracy >= baseline
2. Risk metrics (drawdown, concentration) not worse
3. Sample size gates respected (A/B testing)
4. Fatigue detection produces valid signals
5. Organic channel estimates calibrated to actual outcomes
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from backend.orchestration.event_store import event_store, new_workflow_id

_log = logging.getLogger(__name__)


@dataclass
class ShadowDecision:
    """Paired decision: baseline vs Phase 7-8 new logic."""
    workflow_id: str
    timestamp: str
    decision_type: str  # "capital_allocation", "creative_score", "urgency_rank", etc.

    # Baseline (old path)
    baseline_decision: Any
    baseline_score: float
    baseline_confidence: float

    # New path (Phase 7-8)
    new_decision: Any
    new_score: float
    new_confidence: float

    # Metadata for validation
    product_id: str | None = None
    outcome_realized: dict | None = None  # Set later when outcome known
    validation_status: str = "PENDING"  # PENDING, APPROVED, REJECTED


class ShadowModeController:
    """Manages shadow-mode tracking and validation gates."""

    def __init__(self):
        self.shadow_decisions: dict[str, ShadowDecision] = {}
        self.validation_gates = {
            "accuracy_threshold": 0.95,  # New path must be >= 95% as accurate as baseline
            "risk_threshold": 1.05,  # New path max drawdown <= 105% of baseline
            "sample_size_min": 20,  # A/B test winner gate
            "fatigue_tpr_min": 0.80,  # Fatigue detection true positive rate
            "fatigue_fpr_max": 0.10,  # Fatigue detection false positive rate
            "organic_cac_error_max": 0.20,  # 20% MAPE on organic CAC estimates
            "confidence_interval_coverage_min": 0.88,  # 88% coverage (goal 90%)
        }

    def record_shadow_decision(
        self,
        decision_type: str,
        baseline_decision: Any,
        baseline_score: float,
        baseline_confidence: float,
        new_decision: Any,
        new_score: float,
        new_confidence: float,
        product_id: str | None = None,
    ) -> ShadowDecision:
        """Record a paired decision for shadow-mode validation.

        Args:
            decision_type: "capital_allocation", "creative_score", "urgency_rank", etc.
            baseline_decision: Old path result
            baseline_score: Old path score
            baseline_confidence: Old path confidence
            new_decision: New path (Phase 7-8) result
            new_score: New path score
            new_confidence: New path confidence
            product_id: Product being decided on (for outcome matching)

        Returns:
            ShadowDecision recorded (id-keyed by product/timestamp)
        """
        now = datetime.now(timezone.utc).isoformat()
        workflow_id = new_workflow_id("shadow_mode")

        shadow = ShadowDecision(
            workflow_id=workflow_id,
            timestamp=now,
            decision_type=decision_type,
            baseline_decision=baseline_decision,
            baseline_score=baseline_score,
            baseline_confidence=baseline_confidence,
            new_decision=new_decision,
            new_score=new_score,
            new_confidence=new_confidence,
            product_id=product_id,
        )

        # Store locally
        shadow_id = self._compute_shadow_id(product_id or decision_type, now)
        self.shadow_decisions[shadow_id] = shadow

        # Journal to event store (immutable, audit trail)
        try:
            event_store.append(
                workflow_id,
                "shadow_mode_decision",
                workflow="shadow_mode",
                step=decision_type,
                data={
                    "shadow_id": shadow_id,
                    "product_id": product_id,
                    "baseline": {
                        "decision": str(baseline_decision),
                        "score": round(baseline_score, 4),
                        "confidence": round(baseline_confidence, 4),
                    },
                    "new": {
                        "decision": str(new_decision),
                        "score": round(new_score, 4),
                        "confidence": round(new_confidence, 4),
                    },
                    "agreement": baseline_decision == new_decision,
                },
            )
        except Exception as exc:
            _log.warning(f"Failed to journal shadow decision: {exc}")

        return shadow

    def record_outcome(
        self,
        shadow_id: str,
        realized_roas: float,
        realized_drawdown: float | None = None,
        realized_orders: int = 0,
        fatigue_detected: bool | None = None,
    ) -> None:
        """Record actual outcome for a shadow decision.

        Called later when realized metrics are known (end of campaign, etc.)

        Args:
            shadow_id: ID from record_shadow_decision
            realized_roas: Actual ROAS achieved
            realized_drawdown: Actual portfolio drawdown
            realized_orders: Actual orders generated
            fatigue_detected: If this was a fatigue detection decision, was it correct?
        """
        if shadow_id not in self.shadow_decisions:
            _log.warning(f"Unknown shadow_id: {shadow_id}")
            return

        shadow = self.shadow_decisions[shadow_id]
        shadow.outcome_realized = {
            "roas": realized_roas,
            "drawdown": realized_drawdown,
            "orders": realized_orders,
            "fatigue_detected": fatigue_detected,
        }

        # Validate: did new path predict better?
        # Compare score vs realized_roas
        baseline_error = abs(shadow.baseline_score - realized_roas)
        new_error = abs(shadow.new_score - realized_roas)

        if new_error <= baseline_error:
            shadow.validation_status = "APPROVED"
        else:
            shadow.validation_status = "REJECTED"

        # Journal outcome
        try:
            event_store.append(
                shadow.workflow_id,
                "shadow_mode_outcome",
                workflow="shadow_mode",
                step="outcome_recorded",
                data={
                    "shadow_id": shadow_id,
                    "baseline_error": round(baseline_error, 4),
                    "new_error": round(new_error, 4),
                    "validation_status": shadow.validation_status,
                    "realized": shadow.outcome_realized,
                },
            )
        except Exception as exc:
            _log.warning(f"Failed to journal outcome: {exc}")

    def check_validation_gate(self, decision_type: str) -> tuple[bool, str]:
        """Check if shadow-mode validation for a decision type passes.

        Returns (passes: bool, reason: str)
        """
        relevant = [
            s
            for s in self.shadow_decisions.values()
            if s.decision_type == decision_type and s.outcome_realized is not None
        ]

        if len(relevant) < 50:
            return False, f"Insufficient samples ({len(relevant)} < 50)"

        approved = sum(1 for s in relevant if s.validation_status == "APPROVED")
        approval_rate = approved / len(relevant)

        if approval_rate >= self.validation_gates["accuracy_threshold"]:
            return True, f"Approval rate {approval_rate:.1%} >= {self.validation_gates['accuracy_threshold']:.1%}"
        else:
            return False, f"Approval rate {approval_rate:.1%} < {self.validation_gates['accuracy_threshold']:.1%}"

    def _compute_shadow_id(self, key: str, timestamp: str) -> str:
        """Compute unique shadow ID from product/timestamp."""
        combined = f"{key}:{timestamp}"
        return hashlib.md5(combined.encode()).hexdigest()[:16]


# Global shadow-mode controller
shadow_controller = ShadowModeController()


def shadow_record_decision(
    decision_type: str,
    baseline_decision: Any,
    baseline_score: float,
    baseline_confidence: float,
    new_decision: Any,
    new_score: float,
    new_confidence: float,
    product_id: str | None = None,
) -> str:
    """Convenience function: record shadow decision and return shadow_id."""
    shadow = shadow_controller.record_shadow_decision(
        decision_type=decision_type,
        baseline_decision=baseline_decision,
        baseline_score=baseline_score,
        baseline_confidence=baseline_confidence,
        new_decision=new_decision,
        new_score=new_score,
        new_confidence=new_confidence,
        product_id=product_id,
    )
    return hashlib.md5(
        f"{product_id or decision_type}:{shadow.timestamp}".encode()
    ).hexdigest()[:16]


def shadow_record_outcome(
    shadow_id: str,
    realized_roas: float,
    realized_drawdown: float | None = None,
    realized_orders: int = 0,
) -> None:
    """Convenience function: record outcome for a shadow decision."""
    shadow_controller.record_outcome(
        shadow_id=shadow_id,
        realized_roas=realized_roas,
        realized_drawdown=realized_drawdown,
        realized_orders=realized_orders,
    )
