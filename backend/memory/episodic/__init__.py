"""backend.memory.episodic — raw event and execution history (highest fidelity).

The store is restored from a JSON snapshot on first access and can be
persisted back via ``persist_episodic()`` (called periodically from the
sleep-consolidation worker rather than on every write, since episodes are
high-volume).
"""
from .store import EpisodicStore, Episode

import threading

from backend.core.persistence import save_json_atomic, load_json, state_path

_EPISODIC_PATH = state_path("episodic.json")

_store_instance: EpisodicStore | None = None
_lock = threading.Lock()


def get_episodic_store() -> EpisodicStore:
    global _store_instance
    if _store_instance is None:
        with _lock:
            if _store_instance is None:
                store = EpisodicStore()
                data = load_json(_EPISODIC_PATH)
                if data:
                    store.restore(data)
                _store_instance = store
    return _store_instance


def persist_episodic() -> bool:
    """Write the current episodic store to disk (best-effort)."""
    store = get_episodic_store()
    return save_json_atomic(_EPISODIC_PATH, store.snapshot())


__all__ = ["EpisodicStore", "Episode", "get_episodic_store", "persist_episodic"]
