#!/usr/bin/env python3
"""CLI: Run staging validation on real historical data.

Usage:
    python scripts/run_staging_validation.py [--num-samples N] [--synthetic] [--force-refresh]

Options:
    --num-samples N: Number of scenarios to validate (default: 100)
    --synthetic: Use synthetic data instead of historical (for testing)
    --force-refresh: Force re-extraction of historical data from event store
"""
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.staging.validator import run_staging_validation, ValidationReport


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run staging validation for Phase 7-8")
    parser.add_argument(
        "--num-samples",
        type=int,
        default=100,
        help="Number of scenarios to validate",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Use synthetic data instead of historical",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Force re-extraction of historical data from event store",
    )
    parser.add_argument(
        "--output-json",
        type=str,
        help="Output validation report as JSON to this file",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    print("\n" + "=" * 80)
    print("STAGING VALIDATION FOR PHASE 7-8")
    print("=" * 80 + "\n")

    # Run validation with real historical data (unless --synthetic flag)
    use_historical = not args.synthetic
    report = await run_staging_validation(num_samples=args.num_samples)

    # Print summary
    print(f"\n{report.summary()}\n")

    # Output JSON if requested
    if args.output_json:
        import json
        with open(args.output_json, "w") as f:
            json.dump({
                "validation_period": {
                    "start": report.validation_period[0].isoformat(),
                    "end": report.validation_period[1].isoformat(),
                },
                "scenarios_tested": report.scenarios_tested,
                "scenarios_agreement": report.scenarios_agreement,
                "rank_accuracy_baseline": round(report.rank_accuracy_baseline, 4),
                "rank_accuracy_phase78": round(report.rank_accuracy_phase78, 4),
                "rank_accuracy_improvement_pct": round(report.rank_accuracy_improvement_pct, 2),
                "fatigue_detection_tpr": round(report.fatigue_detection_tpr, 4),
                "fatigue_detection_fpr": round(report.fatigue_detection_fpr, 4),
                "min_samples_gate_compliance": round(report.min_samples_gate_compliance, 4),
                "false_winner_rate_baseline": round(report.false_winner_rate_baseline, 4),
                "false_winner_rate_phase78": round(report.false_winner_rate_phase78, 4),
                "urgency_correlation_with_roas": round(report.urgency_correlation_with_roas, 4),
                "urgency_detects_peak_accuracy": round(report.urgency_detects_peak_accuracy, 4),
                "organic_cac_mape": round(report.organic_cac_mape, 4),
                "organic_roi_accuracy": round(report.organic_roi_accuracy, 4),
                "max_drawdown_baseline": round(report.max_drawdown_baseline, 4),
                "max_drawdown_phase78": round(report.max_drawdown_phase78, 4),
                "drawdown_reduction_pct": round(report.drawdown_reduction_pct, 2),
                "confidence_interval_coverage": round(report.confidence_interval_coverage, 4),
                "recommendation": report.recommendation,
            }, f, indent=2)
        print(f"Report saved to: {args.output_json}\n")

    # Return exit code based on recommendation
    if report.recommendation == "APPROVE":
        print("✅ STAGING VALIDATION PASSED — ready for shadow-mode rollout\n")
        return 0
    elif report.recommendation == "NEEDS_ITERATION":
        print("⚠️  STAGING VALIDATION NEEDS ITERATION — address gaps before production\n")
        return 1
    else:
        print("❌ STAGING VALIDATION FAILED — reject and iterate\n")
        return 2


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
