import random
from typing import Callable


class SignalEngine:
    """Aggregates external demand signals and scores product opportunities."""

    def __init__(self):
        self._sources: list = []

    def register_source(self, name: str, fetch_fn: Callable) -> None:
        """Register a named signal source callable."""
        self._sources.append({"name": name, "fetch": fetch_fn})

    def _mock_signals(self) -> list:
        """Fallback mock signals when no real sources are configured."""
        return [
            {
                "product": f"product_{i}",
                "score": round(random.uniform(0.3, 1.0), 2),
                "source": "mock",
                "market": "global",
                "platform": "meta",
            }
            for i in range(3)
        ]

    def get(self) -> list:
        """Fetch and aggregate signals from all registered sources."""
        if not self._sources:
            return self._mock_signals()

        from backend.discovery.registry import discovery_registry

        all_signals: list = []
        for source in self._sources:
            try:
                signals = source["fetch"]()
                for s in signals:
                    s.setdefault("source", source["name"])
                all_signals.extend(signals)
                discovery_registry.record_fetch(source["name"], len(signals))
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                discovery_registry.record_fetch(source["name"], 0, error=str(exc))

        return all_signals if all_signals else self._mock_signals()

    def filter_opportunities(self, signals: list, min_score: float = 0.5) -> list:
        """Return only signals that meet the minimum score threshold."""
        return [s for s in signals if s.get("score", 0) >= min_score]

    def top_opportunities(self, signals: list, n: int = 5, use_urgency: bool = False) -> list:
        """Return top N signals by score, optionally weighted by urgency (Phase 7).

        If use_urgency=True, rank by urgency = score * velocity * (1 - saturation).
        This prioritizes products that are trending fast with low market saturation.
        """
        if not use_urgency:
            return sorted(signals, key=lambda s: s.get("score", 0), reverse=True)[:n]

        ranked = []
        for s in signals:
            base_score = s.get("score", 0)
            velocity = s.get("velocity", 0.5)  # default 0.5 if not provided
            saturation = s.get("saturation", 0.5)  # default 0.5 if not provided
            urgency = base_score * velocity * (1 - saturation)
            ranked.append((s, urgency))

        return [s for s, _ in sorted(ranked, key=lambda x: -x[1])[:n]]


signal_engine = SignalEngine()

# ── auto-register real adapters ───────────────────────────────────────────────
# Each adapter registers itself if importable; no-op on ImportError.
def _register_adapters() -> None:
    try:
        from backend.adapters.amazon_bestsellers import register as _r1
        _r1(signal_engine)
    except Exception:
        pass
    try:
        from backend.adapters.tiktok_organic import register as _r2
        _r2(signal_engine)
    except Exception:
        pass
    try:
        from backend.adapters.research.trend_source_v1 import register as _r_google
        _r_google(signal_engine)
    except Exception:
        pass
    try:
        from backend.adapters.reddit_trends import register as _r3
        _r3(signal_engine)
    except Exception:
        pass
    try:
        from backend.adapters.youtube_trends import register as _r4
        _r4(signal_engine)
    except Exception:
        pass
    try:
        from backend.adapters.mercadolibre_trends import register as _r5
        _r5(signal_engine)
    except Exception:
        pass
    try:
        from backend.adapters.alibaba_trends import register as _r6
        _r6(signal_engine)
    except Exception:
        pass


_register_adapters()
