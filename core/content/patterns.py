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
    """Thread-safe in-memory registry of accumulated content patterns."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._hook_scores:   dict[str, float] = {}
        self._angle_scores:  dict[str, float] = {}
        self._regime_scores: dict[str, float] = {}

    def update(self, patterns: dict) -> None:
        with self._lock:
            for k, v in patterns.get("hook_scores", {}).items():
                prev = self._hook_scores.get(k)
                self._hook_scores[k] = round((prev + v) / 2, 4) if prev is not None else v
            for k, v in patterns.get("angle_scores", {}).items():
                prev = self._angle_scores.get(k)
                self._angle_scores[k] = round((prev + v) / 2, 4) if prev is not None else v
            for k, v in patterns.get("regime_scores", {}).items():
                prev = self._regime_scores.get(k)
                self._regime_scores[k] = round((prev + v) / 2, 4) if prev is not None else v
        self._persist()

    def snapshot(self) -> dict:
        """Return a JSON-safe dict of current scores for persistence."""
        with self._lock:
            return {
                "hook_scores":   dict(self._hook_scores),
                "angle_scores":  dict(self._angle_scores),
                "regime_scores": dict(self._regime_scores),
            }

    def restore(self, data: dict) -> None:
        """Load hook/angle/regime scores from a previously saved snapshot."""
        with self._lock:
            self._hook_scores   = {k: float(v) for k, v in data.get("hook_scores",   {}).items()}
            self._angle_scores  = {k: float(v) for k, v in data.get("angle_scores",  {}).items()}
            self._regime_scores = {k: float(v) for k, v in data.get("regime_scores", {}).items()}

    def _persist(self) -> None:
        """Write current snapshot to PATTERNSTORE_PATH (fail-silent)."""
        save_json_atomic(_PATTERNSTORE_PATH, self.snapshot())

    def get_top_hooks(self, n: int = 3) -> list[str]:
        with self._lock:
            return sorted(self._hook_scores, key=lambda k: -self._hook_scores[k])[:n]

    def get_top_angles(self, n: int = 3) -> list[str]:
        with self._lock:
            return sorted(self._angle_scores, key=lambda k: -self._angle_scores[k])[:n]

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
