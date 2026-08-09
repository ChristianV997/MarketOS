"""Extract real historical decision/outcome data from event store for staging validation.

Pairs decision events with outcome events to create a comprehensive dataset
for validating Phase 7-8 logic improvements over baseline.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.orchestration.event_store import event_store

_log = logging.getLogger(__name__)


def extract_decision_outcomes(
    lookback_days: int = 90,
    min_sample_size: int = 50,
) -> list[dict]:
    """Extract paired decision/outcome records from event store.

    Looks back N days for:
    1. Decision events (with predicted score, decision type)
    2. Outcome events (with realized ROAS, orders, etc.)

    Returns list of scenarios for staging validation.
    """
    cutoff_ts = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).timestamp()

    # Collect all events, indexed by workflow_id
    all_events = {}
    for event in event_store._iter_events():
        if event.get("ts", 0) < cutoff_ts:
            continue
        wid = event.get("workflow_id", "")
        if wid not in all_events:
            all_events[wid] = []
        all_events[wid].append(event)

    # Pair decisions with outcomes
    scenarios = []
    for wid, events in all_events.items():
        # Find decision and outcome events
        decision_event = None
        outcome_event = None

        for e in events:
            event_type = e.get("event", "")
            step = e.get("step", "")

            # Look for decision events: capital_allocation, product_ranking, launch_decision, etc.
            if event_type == "step_completed" and "decision" in step.lower():
                decision_event = e
            elif event_type == "step_completed" and ("outcome" in step.lower() or "result" in step.lower()):
                outcome_event = e

        if not decision_event or not outcome_event:
            continue

        # Extract decision data
        decision_data = decision_event.get("data", {})
        outcome_data = outcome_event.get("data", {})

        # Build scenario record
        scenario = {
            "workflow_id": wid,
            "timestamp": decision_event.get("ts", 0),
            "decision_type": decision_event.get("step", ""),

            # Decision metrics
            "old_decision": decision_data.get("baseline_decision", ""),
            "old_score": float(decision_data.get("baseline_score", 0.0)),
            "old_confidence": float(decision_data.get("baseline_confidence", 0.6)),

            "new_decision": decision_data.get("new_decision", ""),
            "new_score": float(decision_data.get("new_score", 0.0)),
            "new_confidence": float(decision_data.get("new_confidence", 0.6)),

            # Outcome metrics
            "realized_roas": float(outcome_data.get("roas", 0.0)),
            "realized_drawdown": float(outcome_data.get("drawdown", 0.0)) if "drawdown" in outcome_data else None,
            "realized_orders": int(outcome_data.get("orders", 0)),

            # Product context
            "product_id": decision_data.get("product_id") or outcome_data.get("product_id", ""),
            "category": decision_data.get("category") or outcome_data.get("category", ""),
        }

        scenarios.append(scenario)

    _log.info(
        f"Extracted {len(scenarios)} paired decision/outcome records "
        f"from last {lookback_days} days"
    )

    # Filter by minimum sample size if needed
    if len(scenarios) < min_sample_size:
        _log.warning(
            f"Only {len(scenarios)} scenarios found (min {min_sample_size}). "
            f"Using full dataset; validation may be underpowered."
        )

    return scenarios


def save_scenarios_to_file(
    scenarios: list[dict],
    output_path: str = "data/staging_scenarios.jsonl",
) -> Path:
    """Save extracted scenarios to JSONL file for validator to consume."""
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w") as f:
        for scenario in scenarios:
            f.write(json.dumps(scenario, default=str) + "\n")

    _log.info(f"Saved {len(scenarios)} scenarios to {output_path}")
    return output_file


def load_scenarios_from_file(file_path: str = "data/staging_scenarios.jsonl") -> list[dict]:
    """Load scenarios from JSONL file."""
    scenarios = []
    try:
        with open(file_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    scenarios.append(json.loads(line))
    except FileNotFoundError:
        _log.warning(f"Scenarios file not found: {file_path}")
        return []

    _log.info(f"Loaded {len(scenarios)} scenarios from {file_path}")
    return scenarios


def get_or_create_scenarios(
    lookback_days: int = 90,
    min_sample_size: int = 50,
    force_refresh: bool = False,
) -> list[dict]:
    """Get scenarios from file, or extract from event store if file doesn't exist or force_refresh=True.

    This is the main entry point for validators.
    """
    scenarios_file = Path("data/staging_scenarios.jsonl")

    if scenarios_file.exists() and not force_refresh:
        _log.info("Loading scenarios from cache file")
        return load_scenarios_from_file(str(scenarios_file))

    _log.info("Extracting scenarios from event store (no cache or force_refresh=True)")
    scenarios = extract_decision_outcomes(lookback_days=lookback_days, min_sample_size=min_sample_size)

    if scenarios:
        save_scenarios_to_file(scenarios, str(scenarios_file))

    return scenarios


if __name__ == "__main__":
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Extract from event store and save
    scenarios = get_or_create_scenarios(lookback_days=90, force_refresh=True)
    print(f"Extracted and saved {len(scenarios)} scenarios")
    if scenarios:
        print(f"First scenario:\n{json.dumps(scenarios[0], indent=2, default=str)}")
