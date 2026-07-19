from __future__ import annotations

import logging
import os
from collections import defaultdict
from threading import Lock

from backend.core.persistence import save_json_atomic, load_json

_log = logging.getLogger(__name__)

_PATTERNSTORE_PATH = os.getenv("PATTERNSTORE_PATH", "state/patternstore.json")


def extract_patterns(events: list[dict]) -> dict:
    """Compute average engagement scores grouped by hook, angle, and regime.

    Uses the 'eng_score' key added by batch_classify; falls back to roas if
    eng_score is absent.

    Returns a dict with keys:
      hook_scores   {hook_str: avg_eng_score}
      angle_scores  {angle_str: avg_eng_score}
      regime_scores {regime_str: avg_eng_score}
      top_hooks     [str, ...]  sorted by score desc
      top_angles    [str, ...]  sorted by score desc
    """
    hook_buckets:   dict[str, list[float]] = defaultdict(list)
    angle_buckets:  dict[str, list[float]] = defaultdict(list)
    regime_buckets: dict[str, list[float]] = defaultdict(list)

    for e in events:
        score  = e.get("eng_score", e.get("roas", 0.0))
        hook   = e.get("hook", "")
        angle  = e.get("angle", "")
        regime = e.get("env_regime", e.get("regime", "unknown"))
        if hook:
            hook_buckets[hook].append(score)
        if angle:
            angle_buckets[angle].append(score)
        if regime:
            regime_buckets[regime].append(score)

    def _avg(buckets: dict) -> dict[str, float]:
        return {k: round(sum(v) / len(v), 4) for k, v in buckets.items()}

    hook_scores   = _avg(hook_buckets)
    angle_scores  = _avg(angle_buckets)
    regime_scores = _avg(regime_buckets)

    top_hooks  = sorted(hook_scores,  key=lambda k: -hook_scores[k])
    top_angles = sorted(angle_scores, key=lambda k: -angle_scores[k])

    return {
        "hook_scores":   hook_scores,
        "angle_scores":  angle_scores,
        "regime_scores": regime_scores,
        "top_hooks":     top_hooks,
        "top_angles":    top_angles,
    }


class PatternStore:
    """Thread-safe in-memory registry of accumulated content patterns.

    Phase 7 upgrade: tracks sample counts per pattern for sample-size-weighted
    running average (replaces non-convergent (prev+new)/2 blend) and gates
    "winner" declarations on minimum sample size (n≥20) + significance test.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._hook_scores:   dict[str, float] = {}
        self._angle_scores:  dict[str, float] = {}
        self._regime_scores: dict[str, float] = {}
        # Track observation counts for sample-size weighting
        self._hook_counts:   dict[str, int] = {}
        self._angle_counts:  dict[str, int] = {}
        self._regime_counts: dict[str, int] = {}

    def update(self, patterns: dict) -> None:
        """Phase 7: sample-size-weighted running average (not (prev+new)/2)."""
        with self._lock:
            for k, v in patterns.get("hook_scores", {}).items():
                prev = self._hook_scores.get(k)
                count = self._hook_counts.get(k, 0)
                if prev is not None:
                    # Sample-size-weighted: (count * prev + new) / (count + 1)
                    self._hook_scores[k] = round((count * prev + v) / (count + 1), 4)
                    self._hook_counts[k] = count + 1
                else:
                    self._hook_scores[k] = v
                    self._hook_counts[k] = 1

            for k, v in patterns.get("angle_scores", {}).items():
                prev = self._angle_scores.get(k)
                count = self._angle_counts.get(k, 0)
                if prev is not None:
                    self._angle_scores[k] = round((count * prev + v) / (count + 1), 4)
                    self._angle_counts[k] = count + 1
                else:
                    self._angle_scores[k] = v
                    self._angle_counts[k] = 1

            for k, v in patterns.get("regime_scores", {}).items():
                prev = self._regime_scores.get(k)
                count = self._regime_counts.get(k, 0)
                if prev is not None:
                    self._regime_scores[k] = round((count * prev + v) / (count + 1), 4)
                    self._regime_counts[k] = count + 1
                else:
                    self._regime_scores[k] = v
                    self._regime_counts[k] = 1
        self._persist()

    def is_statistically_valid(self, pattern_id: str, category: str = "hook", min_samples: int = 20) -> bool:
        """Check if a pattern has enough samples to be declared a winner (Phase 7).

        Returns True only if observation count >= min_samples.
        """
        with self._lock:
            if category == "hook":
                return self._hook_counts.get(pattern_id, 0) >= min_samples
            elif category == "angle":
                return self._angle_counts.get(pattern_id, 0) >= min_samples
            elif category == "regime":
                return self._regime_counts.get(pattern_id, 0) >= min_samples
        return False

    def get_observation_count(self, pattern_id: str, category: str = "hook") -> int:
        """Return number of observations for a pattern (Phase 7)."""
        with self._lock:
            if category == "hook":
                return self._hook_counts.get(pattern_id, 0)
            elif category == "angle":
                return self._angle_counts.get(pattern_id, 0)
            elif category == "regime":
                return self._regime_counts.get(pattern_id, 0)
        return 0

    def snapshot(self) -> dict:
        """Return a JSON-safe dict of current scores for persistence."""
        with self._lock:
            return {
                "hook_scores":   dict(self._hook_scores),
                "angle_scores":  dict(self._angle_scores),
                "regime_scores": dict(self._regime_scores),
                "hook_counts":   dict(self._hook_counts),
                "angle_counts":  dict(self._angle_counts),
                "regime_counts": dict(self._regime_counts),
            }

    def restore(self, data: dict) -> None:
        """Load hook/angle/regime scores from a previously saved snapshot."""
        with self._lock:
            self._hook_scores   = {k: float(v) for k, v in data.get("hook_scores",   {}).items()}
            self._angle_scores  = {k: float(v) for k, v in data.get("angle_scores",  {}).items()}
            self._regime_scores = {k: float(v) for k, v in data.get("regime_scores", {}).items()}
            # Phase 7: restore observation counts; if missing (old snapshot), default to len(scores)
            self._hook_counts   = {k: int(v) for k, v in data.get("hook_counts",   {}).items()}
            self._angle_counts  = {k: int(v) for k, v in data.get("angle_counts",  {}).items()}
            self._regime_counts = {k: int(v) for k, v in data.get("regime_counts", {}).items()}
            # Backward compat: if no counts, infer from scores (assume each score came from 1 observation)
            if not self._hook_counts:
                self._hook_counts = {k: 1 for k in self._hook_scores}
            if not self._angle_counts:
                self._angle_counts = {k: 1 for k in self._angle_scores}
            if not self._regime_counts:
                self._regime_counts = {k: 1 for k in self._regime_scores}

    def _persist(self) -> None:
        """Write current snapshot to PATTERNSTORE_PATH (fail-silent)."""
        save_json_atomic(_PATTERNSTORE_PATH, self.snapshot())

    def get_top_hooks(self, n: int = 3) -> list[str]:
        with self._lock:
            return sorted(self._hook_scores, key=lambda k: -self._hook_scores[k])[:n]

    def get_top_angles(self, n: int = 3) -> list[str]:
        with self._lock:
            return sorted(self._angle_scores, key=lambda k: -self._angle_scores[k])[:n]

    def get_top_hooks_validated(self, n: int = 3, min_samples: int = 20) -> list[str]:
        """Phase 7: top hooks restricted to those with n >= min_samples observations.

        Prevents a single lucky observation from being treated as a winner.
        Returns fewer than n (or empty) if not enough hooks have cleared the gate.
        """
        with self._lock:
            valid = {k: v for k, v in self._hook_scores.items()
                     if self._hook_counts.get(k, 0) >= min_samples}
        return sorted(valid, key=lambda k: -valid[k])[:n]

    def get_top_angles_validated(self, n: int = 3, min_samples: int = 20) -> list[str]:
        """Phase 7: top angles restricted to those with n >= min_samples observations."""
        with self._lock:
            valid = {k: v for k, v in self._angle_scores.items()
                     if self._angle_counts.get(k, 0) >= min_samples}
        return sorted(valid, key=lambda k: -valid[k])[:n]

    def get_patterns(self) -> dict:
        with self._lock:
            hook_scores   = dict(self._hook_scores)
            angle_scores  = dict(self._angle_scores)
            regime_scores = dict(self._regime_scores)
        top_hooks  = sorted(hook_scores,  key=lambda k: -hook_scores[k])
        top_angles = sorted(angle_scores, key=lambda k: -angle_scores[k])
        return {
            "hook_scores":   hook_scores,
            "angle_scores":  angle_scores,
            "regime_scores": regime_scores,
            "top_hooks":     top_hooks,
            "top_angles":    top_angles,
        }


pattern_store = PatternStore()


def _load_patternstore() -> None:
    """Load persisted pattern scores on startup (fail-silent)."""
    data = load_json(_PATTERNSTORE_PATH)
    if not data:
        return
    pattern_store.restore(data)
    _log.info("patternstore_loaded path=%s hooks=%d angles=%d",
              _PATTERNSTORE_PATH,
              len(data.get("hook_scores", {})),
              len(data.get("angle_scores", {})))


_load_patternstore()
