#!/usr/bin/env python
"""backend.monitoring.production_monitor — Week 3-6 continuous monitoring.

Real-time dashboard and alerting for production deployment.
Runs as cron job monthly, or manually for real-time checks.

Usage:
    python backend/monitoring/production_monitor.py --summary
    python backend/monitoring/production_monitor.py --alerts
    python backend/monitoring/production_monitor.py --report
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np


@dataclass
class PhaseMetric:
    """One phase's validation metric."""
    phase: str
    metric_name: str
    value: float
    baseline: float
    alert_min: float
    alert_max: float

    @property
    def status(self) -> str:
        if self.value < self.alert_min or self.value > self.alert_max:
            return "🔴 CRITICAL"
        elif abs(self.value - self.baseline) / (self.baseline or 1) > 0.05:
            return "🟡 WARNING"
        return "🟢 OK"

    @property
    def variance_pct(self) -> float:
        if self.baseline <= 0:
            return 0.0
        return abs(self.value - self.baseline) / self.baseline * 100


class ProductionMonitor:
    """Monitor production deployment across 6 live phases."""

    BASELINE_METRICS = {
        "capital_policy": {
            "allocations_valid_pct": {"baseline": 1.0, "alert_min": 0.99, "alert_max": 1.0},
            "budget_respected_pct": {"baseline": 1.0, "alert_min": 0.99, "alert_max": 1.0},
        },
        "regime_detection": {
            "changepoint_detection_rate": {"baseline": 0.025, "alert_min": 0.01, "alert_max": 0.15},
        },
        "calibration": {
            "valid_train_holdout_split_pct": {"baseline": 0.98, "alert_min": 0.95, "alert_max": 1.0},
        },
        "adaptive_risk": {
            "adaptive_more_permissive_pct": {"baseline": 1.0, "alert_min": 0.99, "alert_max": 1.0},
        },
        "geo_economics": {
            "margin_adjusted_lte_raw_pct": {"baseline": 1.0, "alert_min": 0.99, "alert_max": 1.0},
        },
        "regime_confidence": {
            "bonus_adjusted_lte_raw_pct": {"baseline": 1.0, "alert_min": 0.99, "alert_max": 1.0},
        },
    }

    def __init__(self):
        self.event_store_path = os.path.join(
            os.getenv("STATE_DIR", "state"), "workflow_executions.jsonl"
        )
        self.validation_results = {}

    def load_validation_results(self) -> dict:
        """Load latest validation results from shadow_validator_v2."""
        try:
            from backend.validation.shadow_validator_v2 import validate_all_phases_v2
            return validate_all_phases_v2()
        except Exception as e:
            print(f"Warning: Could not load validation results: {e}", file=sys.stderr)
            return {}

    def check_phase_status(self) -> dict[str, PhaseMetric]:
        """Check all phase metrics against baselines."""
        results = self.load_validation_results()
        metrics = {}

        for phase_name, phase_metrics in self.BASELINE_METRICS.items():
            if phase_name not in results:
                continue

            phase_result = results[phase_name]
            if phase_result.get("status") == "insufficient_data":
                continue

            for metric_name, thresholds in phase_metrics.items():
                value = phase_result.get("metrics", {}).get(metric_name, 0)

                metric = PhaseMetric(
                    phase=phase_name,
                    metric_name=metric_name,
                    value=value,
                    baseline=thresholds["baseline"],
                    alert_min=thresholds["alert_min"],
                    alert_max=thresholds["alert_max"],
                )
                metrics[f"{phase_name}:{metric_name}"] = metric

        return metrics

    def check_capital(self) -> dict:
        """Check current capital state."""
        try:
            from backend.core.state import SystemState

            state = SystemState()
            return {
                "capital": state.capital,
                "total_cycles": state.total_cycles,
                "regime": state.detected_regime,
                "transition_cooldown": state.transition_cooldown,
            }
        except Exception as e:
            print(f"Warning: Could not load state: {e}", file=sys.stderr)
            return {}

    def print_summary(self):
        """Print executive summary."""
        print("\n" + "=" * 80)
        print("MARKETOS PRODUCTION MONITORING SUMMARY")
        print("=" * 80)
        print(f"Timestamp: {datetime.now().isoformat()}")

        # Phase status
        metrics = self.check_phase_status()
        print("\n📊 PHASE STATUS:")
        print("-" * 80)

        critical_count = 0
        warning_count = 0

        for key, metric in sorted(metrics.items()):
            status = metric.status
            variance = metric.variance_pct
            print(
                f"{status} {metric.phase:25} {metric.metric_name:30} "
                f"= {metric.value:.4f} (baseline: {metric.baseline:.4f}, "
                f"variance: {variance:+.1f}%)"
            )

            if "CRITICAL" in status:
                critical_count += 1
            elif "WARNING" in status:
                warning_count += 1

        # Capital status
        capital = self.check_capital()
        print("\n💰 CAPITAL STATUS:")
        print("-" * 80)
        if capital:
            print(f"  Current Capital:       ${capital.get('capital', 0):>10,.0f}")
            print(f"  Total Cycles:          {capital.get('total_cycles', 0):>10d}")
            print(f"  Detected Regime:       {capital.get('regime', 'unknown'):>10}")
            print(f"  Transition Cooldown:   {capital.get('transition_cooldown', 0):>10d} cycles")

        # Alert summary
        print("\n⚠️  ALERT SUMMARY:")
        print("-" * 80)
        print(f"  🔴 Critical Issues: {critical_count}")
        print(f"  🟡 Warnings:        {warning_count}")
        print(f"  🟢 Nominal:         {len(metrics) - critical_count - warning_count}")

        print("\n" + "=" * 80)

        if critical_count > 0:
            print("ACTION REQUIRED: Critical issues detected. See alerts below.")
            sys.exit(1)

    def print_alerts(self):
        """Print detailed alerts."""
        metrics = self.check_phase_status()
        alerts = [m for m in metrics.values() if "CRITICAL" in m.status or "WARNING" in m.status]

        if not alerts:
            print("✅ No alerts. System nominal.")
            return

        print("\n" + "=" * 80)
        print("ALERTS & RECOMMENDATIONS")
        print("=" * 80)

        for metric in sorted(alerts, key=lambda m: m.status, reverse=True):
            print(f"\n{metric.status}")
            print(f"  Phase:        {metric.phase}")
            print(f"  Metric:       {metric.metric_name}")
            print(f"  Current:      {metric.value:.4f}")
            print(f"  Baseline:     {metric.baseline:.4f}")
            print(f"  Variance:     {metric.variance_pct:+.1f}%")
            print(f"  Valid Range:  [{metric.alert_min:.4f}, {metric.alert_max:.4f}]")

            # Recommendations
            if metric.value < metric.alert_min:
                print(
                    f"  → Value below minimum. "
                    f"Check {metric.phase} event_store for anomalies."
                )
            elif metric.value > metric.alert_max:
                print(
                    f"  → Value above maximum. "
                    f"May indicate over-aggressive tuning."
                )
            else:
                print(
                    f"  → Value drifting from baseline but within alert range. "
                    f"Monitor over next 24 hours."
                )

        print("\n" + "=" * 80)

    def print_report(self, output_file: str | None = None):
        """Generate full JSON report."""
        report = {
            "timestamp": datetime.now().isoformat(),
            "metrics": {},
            "capital": self.check_capital(),
        }

        metrics = self.check_phase_status()
        for key, metric in metrics.items():
            report["metrics"][key] = {
                "value": float(metric.value),
                "baseline": float(metric.baseline),
                "status": metric.status,
                "variance_pct": float(metric.variance_pct),
            }

        if output_file:
            with open(output_file, "w") as f:
                json.dump(report, f, indent=2)
            print(f"Report saved to {output_file}")
        else:
            print(json.dumps(report, indent=2))

        return report


def main():
    parser = argparse.ArgumentParser(
        description="Production monitoring for MarketOS Week 3-6 deployment"
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print executive summary (default)"
    )
    parser.add_argument("--alerts", action="store_true", help="Print detailed alerts")
    parser.add_argument("--report", action="store_true", help="Print full JSON report")
    parser.add_argument(
        "--output", type=str, help="Save JSON report to file (with --report)"
    )

    args = parser.parse_args()

    monitor = ProductionMonitor()

    if args.alerts:
        monitor.print_alerts()
    elif args.report:
        monitor.print_report(args.output)
    else:
        monitor.print_summary()


if __name__ == "__main__":
    main()
