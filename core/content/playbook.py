from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from threading import Lock

from core.content.patterns import extract_patterns
from backend.core.persistence import save_json_atomic, load_json, state_path

_PLAYBOOK_PATH = state_path("playbook.json")


@dataclass
class Playbook:
    product: str
    phase: str
    top_hooks: list[str]
    top_angles: list[str]
    estimated_roas: float
    confidence: float
    evidence_count: int
    created_at: float = field(default_factory=time.time)
    last_launched_at: float = 0.0


class PlaybookMemory:
    """In-memory store keyed by (product, phase)."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._store: dict[tuple[str, str], Playbook] = {}

    def upsert(self, playbook: Playbook) -> None:
        key = (playbook.product, playbook.phase)
        with self._lock:
            existing = self._store.get(key)
            if existing:
                # Merge: update hooks/angles and average ROAS estimate
                merged_roas = round(
                    (existing.estimated_roas * existing.evidence_count
                     + playbook.estimated_roas * playbook.evidence_count)
                    / (existing.evidence_count + playbook.evidence_count),
                    4,
                )
                total = existing.evidence_count + playbook.evidence_count
                self._store[key] = Playbook(
                    product=playbook.product,
                    phase=playbook.phase,
                    top_hooks=playbook.top_hooks or existing.top_hooks,
                    top_angles=playbook.top_angles or existing.top_angles,
                    estimated_roas=merged_roas,
                    confidence=round(total / (total + 10), 4),
                    evidence_count=total,
                    created_at=existing.created_at,
                    last_launched_at=existing.last_launched_at,
                )
            else:
                self._store[key] = playbook
        self._persist()

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [asdict(pb) for pb in self._store.values()]

    def restore(self, rows: list[dict]) -> None:
        with self._lock:
            self._store.clear()
            for d in rows or []:
                try:
                    pb = Playbook(**d)
                except Exception:
                    continue
                self._store[(pb.product, pb.phase)] = pb

    def _persist(self) -> None:
        save_json_atomic(_PLAYBOOK_PATH, self.snapshot())

    def get(self, product: str, phase: str | None = None) -> Playbook | None:
        with self._lock:
            if phase:
                return self._store.get((product, phase))
            # Return highest-confidence playbook for this product
            candidates = [pb for (p, _), pb in self._store.items() if p == product]
            return max(candidates, key=lambda pb: pb.confidence, default=None)

    def all(self) -> list[Playbook]:
        with self._lock:
            return list(self._store.values())

    def mark_launched(self, product: str, phase: str, ts: float) -> None:
        """Stamp last_launched_at after a real campaign launch, so a
        relaunch-cooldown check (backend/orchestration's _run_scaling) can
        avoid minting a fresh campaign for the same playbook every tick."""
        with self._lock:
            key = (product, phase)
            existing = self._store.get(key)
            if existing is None:
                return
            existing.last_launched_at = ts
        self._persist()


def generate_playbook(
    product: str,
    events: list[dict],
    phase: str = "EXPLORE",
) -> Playbook:
    """Build a Playbook from a classified event list."""
    patterns = extract_patterns(events)
    top_hooks  = patterns.get("top_hooks", [])[:3]
    top_angles = patterns.get("top_angles", [])[:3]

    roas_vals = [e.get("roas", 0.0) for e in events if e.get("roas") is not None]
    estimated_roas = round(sum(roas_vals) / len(roas_vals), 4) if roas_vals else 0.0

    n = len(events)
    confidence = round(n / (n + 10), 4)

    return Playbook(
        product=product,
        phase=phase,
        top_hooks=top_hooks,
        top_angles=top_angles,
        estimated_roas=estimated_roas,
        confidence=confidence,
        evidence_count=n,
    )


playbook_memory = PlaybookMemory()

# Restore persisted playbooks on import (fail-silent)
_saved = load_json(_PLAYBOOK_PATH)
if _saved:
    playbook_memory.restore(_saved)
