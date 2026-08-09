#!/usr/bin/env python3
"""Profile hottest code paths to identify optimization targets."""
import sys
sys.path.insert(0, "/home/user/my_OS")

import cProfile
import pstats
import io
from pstats import SortKey

# Test scenarios
def profile_discovery():
    """Profile product discovery (signal fetching)."""
    from backend.discovery import discover_products
    discover_products("shoes", limit=10)


def profile_validation():
    """Profile supplier validation."""
    from backend.validation.suppliers import quote_all
    products = [
        {"name": "Test Product", "url": "https://example.com", "price": 29.99}
        for _ in range(3)
    ]
    quote_all(products)


def profile_metrics():
    """Profile metrics aggregation."""
    from backend.metrics.campaign_metrics import campaign_performance
    campaign_performance(lookback_days=1)


def profile_profitability():
    """Profile profitability calculation."""
    from backend.metrics.profitability import calculate_profitability
    calculate_profitability(lookback_days=1)


def profile_dropship_cycle():
    """Profile full dropship cycle."""
    from backend.dropship import run_dropship_cycle
    run_dropship_cycle(max_products=2, budget_daily=50.0)


profiles = {
    "discovery": profile_discovery,
    "validation": profile_validation,
    "metrics": profile_metrics,
    "profitability": profile_profitability,
    "dropship": profile_dropship_cycle,
}


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "dropship"

    if target not in profiles:
        print(f"Unknown profile: {target}")
        print(f"Available: {', '.join(profiles.keys())}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"Profiling: {target}")
    print(f"{'='*60}\n")

    pr = cProfile.Profile()
    pr.enable()
    try:
        profiles[target]()
    except Exception as e:
        print(f"Error during profiling: {e}")
    finally:
        pr.disable()

    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats(SortKey.CUMULATIVE)
    ps.print_stats(20)  # Top 20 functions
    print(s.getvalue())

    print("\n" + "="*60)
    print("Top hotspots by cumulative time (first 10):")
    print("="*60)
    ps2 = pstats.Stats(pr).sort_stats(SortKey.CUMULATIVE)
    ps2.print_stats(10)
