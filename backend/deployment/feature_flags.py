"""Feature flag management for Phase 7-8 production deployment.

Flags enable gradual rollout with rollback capability:
- PHASE7_FATIGUE_DETECTION_LIVE: Hook/sequence fatigue detection (rolling-window)
- PHASE7_AB_TEST_VALIDITY_LIVE: Min sample size gates (n>=20) for A/B test winners
- PHASE7_URGENCY_SCORING_LIVE: Product ranking by urgency (velocity * saturation)
- PHASE7_MONTE_CARLO_LIVE: Confidence intervals for pre-launch risk modeling
- PHASE8_ORGANIC_CHANNEL_LIVE: Organic/UGC channel in capital allocation
- PHASE8_AFFILIATE_SCALING_LIVE: Affiliate network recruitment and scaling

Shadow mode:
- All flags default FALSE (baseline logic runs)
- Both old and new paths compute and journal decisions
- After validation gates clear, flag is flipped to TRUE (new path controls)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any


class FeatureFlag(str, Enum):
    """Available feature flags for Phase 7-8 rollout."""
    PHASE7_FATIGUE_DETECTION_LIVE = "PHASE7_FATIGUE_DETECTION_LIVE"
    PHASE7_AB_TEST_VALIDITY_LIVE = "PHASE7_AB_TEST_VALIDITY_LIVE"
    PHASE7_URGENCY_SCORING_LIVE = "PHASE7_URGENCY_SCORING_LIVE"
    PHASE7_MONTE_CARLO_LIVE = "PHASE7_MONTE_CARLO_LIVE"
    PHASE8_ORGANIC_CHANNEL_LIVE = "PHASE8_ORGANIC_CHANNEL_LIVE"
    PHASE8_AFFILIATE_SCALING_LIVE = "PHASE8_AFFILIATE_SCALING_LIVE"


@dataclass
class FlagConfig:
    """Configuration for a single feature flag."""
    name: FeatureFlag
    description: str
    enabled: bool
    shadow_mode: bool  # If True, both paths run; if False, only enabled path runs
    validation_gate: str = ""  # Gate that must pass before flipping to live
    created_at: datetime = None
    flipped_at: datetime | None = None
    rollback_plan: str = ""

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)


class FeatureFlagManager:
    """Manages Phase 7-8 feature flags for staged production rollout."""

    # Default flag configuration
    DEFAULT_FLAGS = {
        FeatureFlag.PHASE7_FATIGUE_DETECTION_LIVE: FlagConfig(
            name=FeatureFlag.PHASE7_FATIGUE_DETECTION_LIVE,
            description="Hook/sequence fatigue detection via rolling-window ROAS decline",
            enabled=False,
            shadow_mode=True,
            validation_gate="fatigue_detection_tpr>=0.80,fpr<=0.10",
            rollback_plan="Resume lifetime-average scoring for hooks/sequences",
        ),
        FeatureFlag.PHASE7_AB_TEST_VALIDITY_LIVE: FlagConfig(
            name=FeatureFlag.PHASE7_AB_TEST_VALIDITY_LIVE,
            description="A/B test validity gates (min n>=20) before winner declaration",
            enabled=False,
            shadow_mode=True,
            validation_gate="false_winner_rate_phase78 < baseline",
            rollback_plan="Allow single-observation patterns to be declared winners",
        ),
        FeatureFlag.PHASE7_URGENCY_SCORING_LIVE: FlagConfig(
            name=FeatureFlag.PHASE7_URGENCY_SCORING_LIVE,
            description="Product ranking by urgency (score * velocity * (1-saturation))",
            enabled=False,
            shadow_mode=True,
            validation_gate="urgency_correlation_with_roas>=0.65",
            rollback_plan="Resume score-only ranking",
        ),
        FeatureFlag.PHASE7_MONTE_CARLO_LIVE: FlagConfig(
            name=FeatureFlag.PHASE7_MONTE_CARLO_LIVE,
            description="Monte Carlo confidence intervals for pre-launch risk modeling",
            enabled=False,
            shadow_mode=True,
            validation_gate="confidence_interval_coverage>=0.88",
            rollback_plan="Resume point-estimate scoring without intervals",
        ),
        FeatureFlag.PHASE8_ORGANIC_CHANNEL_LIVE: FlagConfig(
            name=FeatureFlag.PHASE8_ORGANIC_CHANNEL_LIVE,
            description="Organic/UGC channel in capital allocation (80/20 paid vs organic)",
            enabled=False,
            shadow_mode=True,
            validation_gate="organic_cac_mape<=0.15",
            rollback_plan="100% paid channel (Meta + TikTok only)",
        ),
        FeatureFlag.PHASE8_AFFILIATE_SCALING_LIVE: FlagConfig(
            name=FeatureFlag.PHASE8_AFFILIATE_SCALING_LIVE,
            description="Auto-recruit affiliates from networks (impact.com, Refersion, CJ)",
            enabled=False,
            shadow_mode=True,
            validation_gate="affiliate_roas_baseline>=2.0,ctr>=0.04",
            rollback_plan="Manual affiliate recruitment only",
        ),
    }

    def __init__(self):
        self.flags: dict[FeatureFlag, FlagConfig] = {}
        self._load_flags()

    def _load_flags(self) -> None:
        """Load flags from environment or defaults."""
        for flag_enum, default_config in self.DEFAULT_FLAGS.items():
            env_var = flag_enum.value
            enabled = os.getenv(env_var, "false").lower() == "true"
            shadow = os.getenv(f"{env_var}_SHADOW", "true").lower() == "true"

            config = FlagConfig(
                name=flag_enum,
                description=default_config.description,
                enabled=enabled,
                shadow_mode=shadow,
                validation_gate=default_config.validation_gate,
                rollback_plan=default_config.rollback_plan,
                created_at=default_config.created_at,
            )

            if enabled and not config.flipped_at:
                config.flipped_at = datetime.now(timezone.utc)

            self.flags[flag_enum] = config

    def is_enabled(self, flag: FeatureFlag) -> bool:
        """Check if flag is live (controls behavior)."""
        return self.flags.get(flag, self.DEFAULT_FLAGS[flag]).enabled

    def is_shadow_mode(self, flag: FeatureFlag) -> bool:
        """Check if flag is in shadow mode (both paths run)."""
        return self.flags.get(flag, self.DEFAULT_FLAGS[flag]).shadow_mode

    def flip_flag(self, flag: FeatureFlag, enabled: bool) -> tuple[bool, str]:
        """Flip a flag from shadow to live (or disable).

        Returns (success: bool, message: str)
        """
        if flag not in self.flags:
            return False, f"Unknown flag: {flag}"

        config = self.flags[flag]

        if enabled == config.enabled:
            return False, f"Flag already {('enabled' if enabled else 'disabled')}"

        # If enabling (shadow → live), log the gate requirement
        if enabled and not config.flipped_at:
            config.flipped_at = datetime.now(timezone.utc)

        config.enabled = enabled

        # Update environment variable (for subprocesses)
        os.environ[flag.value] = "true" if enabled else "false"

        action = "ENABLED" if enabled else "DISABLED"
        return True, f"Flag {flag.value} {action}"

    def get_deployment_checklist(self) -> dict[FeatureFlag, dict[str, Any]]:
        """Return deployment checklist for all Phase 7-8 flags."""
        return {
            flag: {
                "name": flag.value,
                "description": config.description,
                "enabled": config.enabled,
                "shadow_mode": config.shadow_mode,
                "validation_gate": config.validation_gate,
                "rollback_plan": config.rollback_plan,
                "created_at": config.created_at.isoformat(),
                "flipped_at": config.flipped_at.isoformat() if config.flipped_at else None,
                "days_since_flip": (
                    (datetime.now(timezone.utc) - config.flipped_at).days
                    if config.flipped_at
                    else None
                ),
            }
            for flag, config in self.flags.items()
        }

    def generate_deployment_report(self) -> str:
        """Generate human-readable deployment status report."""
        lines = [
            "=" * 80,
            "Phase 7-8 Feature Flag Deployment Report",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            "=" * 80,
            "",
        ]

        checklist = self.get_deployment_checklist()
        for flag, info in checklist.items():
            status = "🔴 SHADOW" if info["shadow_mode"] else ("🟢 LIVE" if info["enabled"] else "⚫ OFF")
            lines.append(f"{status}  {info['name']}")
            lines.append(f"     Description: {info['description']}")
            lines.append(f"     Gate: {info['validation_gate']}")
            if info['flipped_at']:
                lines.append(f"     Flipped: {info['flipped_at']} ({info['days_since_flip']} days ago)")
            lines.append("")

        lines.extend([
            "",
            "Deployment Strategy",
            "1. All flags start in SHADOW mode (shadow_mode=true, enabled=false)",
            "2. Both old and new paths compute and journal decisions",
            "3. Validation gates must pass before flipping to LIVE",
            "4. Once LIVE (shadow_mode=false, enabled=true), new path controls behavior",
            "5. Rollback: flip enabled=false to revert to baseline",
            "",
        ])

        return "\n".join(lines)


# Global flag manager
flag_manager = FeatureFlagManager()


def should_use_new_logic(flag: FeatureFlag) -> bool:
    """Convenience function: check if new path should be used."""
    if flag_manager.is_shadow_mode(flag):
        # Both paths run; caller must handle both
        return True  # Signal: compute new path (caller also computes old)

    # Shadow mode off: use enabled state
    return flag_manager.is_enabled(flag)


def should_log_shadow_decision(flag: FeatureFlag) -> bool:
    """Convenience function: check if decision should be shadowed."""
    return flag_manager.is_shadow_mode(flag)


if __name__ == "__main__":
    manager = FeatureFlagManager()
    print(manager.generate_deployment_report())
