from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

from .source_calibration import CalibrationRun, SourceCalibrationProfile, SourceUsefulnessSignal

_log = logging.getLogger(__name__)


class CalibrationRegistry:
    def __init__(self, path=None):
        self.path = Path(path or os.getenv("MARKETOS_CALIBRATION_STATE", "state/source_calibration_registry.json")); self.signals = {}; self.profiles = {}; self.runs = {}; self._lock = threading.RLock(); self.last_save_ok = True; self.load()
    def register_signal(self, signal): self.signals[signal.signal_id] = signal; self.save(); return signal
    def register_signals(self, signals):
        for signal in signals: self.signals[signal.signal_id] = signal
        self.save(); return signals
    def list_signals(self, workspace_id=None, source_name=None, parser_type=None, signal_type=None, limit=100): return list(self.signals.values())[:max(0, min(int(limit), 1000))] if not any([workspace_id, source_name, parser_type, signal_type]) else [x for x in self.signals.values() if (workspace_id is None or x.workspace_id == workspace_id) and (source_name is None or x.source_name == source_name) and (parser_type is None or x.parser_type == parser_type) and (signal_type is None or x.signal_type == signal_type)][:max(0, min(int(limit), 1000))]
    def register_profile(self, profile):
        key = (profile.workspace_id, profile.source_name, profile.parser_type)
        for existing_id in [pid for pid, item in self.profiles.items() if pid != profile.profile_id and (item.workspace_id, item.source_name, item.parser_type) == key]:
            del self.profiles[existing_id]
        self.profiles[profile.profile_id] = profile; self.save(); return profile
    def get_profile(self, source_name, parser_type=None, workspace_id=None):
        # Without a workspace there is no tenant to read from, so the answer is None rather than another workspace's profile.
        if workspace_id is None: return None
        for profile in self.profiles.values():
            if profile.source_name == source_name and (parser_type is None or profile.parser_type == parser_type) and profile.workspace_id == workspace_id: return profile
        return None
    def profiles_for_parser(self, workspace_id, parser_type):
        return sorted((x for x in self.profiles.values() if x.workspace_id == workspace_id and x.parser_type == parser_type), key=lambda x: (x.source_name, x.profile_id))
    def list_profiles(self, workspace_id=None, parser_type=None, limit=100): return [x for x in self.profiles.values() if (workspace_id is None or x.workspace_id == workspace_id) and (parser_type is None or x.parser_type == parser_type)][:max(0, min(int(limit), 500))]
    def register_calibration_run(self, run): self.runs[run.calibration_id] = run; self.save(); return run
    def get_calibration_run(self, calibration_id): return self.runs.get(calibration_id)
    def list_calibration_runs(self, workspace_id=None, limit=50): return list(reversed([x for x in self.runs.values() if workspace_id is None or x.workspace_id == workspace_id]))[:max(0, min(int(limit), 500))]
    def clear_for_tests(self): self.signals.clear(); self.profiles.clear(); self.runs.clear(); self.save()
    def to_dict(self): return {"signals": {k: v.to_dict() for k, v in self.signals.items()}, "profiles": {k: v.to_dict() for k, v in self.profiles.items()}, "runs": {k: v.to_dict() for k, v in self.runs.items()}}
    def load(self):
        try:
            if not self.path.exists(): return
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            signals = raw.get("signals", {}); profiles = raw.get("profiles", {})
            # Records written before attribution and policy versioning are not verifiable, so they stay out of every adjustment.
            for item in signals.values():
                if "attribution" not in item: item.update(attribution="legacy_unverified", exclusion_reason="legacy_unverified")
            for item in profiles.values():
                if "policy_version" not in item: item.update(evidence_status="legacy_unverified", recommended_priority_adjustment=0.0, confidence_multiplier_adjustment=1.0)
            self.signals = {k: SourceUsefulnessSignal.from_dict(v) for k, v in signals.items()}; self.profiles = {k: SourceCalibrationProfile.from_dict(v) for k, v in profiles.items()}; self.runs = {k: CalibrationRun.from_dict(v) for k, v in raw.get("runs", {}).items()}
        except Exception as exc:
            # Keep the unreadable file for inspection; the next save must not silently overwrite it.
            _log.warning("calibration registry unreadable; moved aside and starting empty: %s", type(exc).__name__)
            try: os.replace(self.path, self.path.with_name(self.path.name + ".unreadable"))
            except OSError: pass
            self.signals, self.profiles, self.runs = {}, {}, {}
    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True); temp = self.path.with_suffix(".tmp"); temp.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8"); temp.replace(self.path); self.last_save_ok = True
        except Exception as exc:
            self.last_save_ok = False
            _log.warning("calibration registry save failed: %s", type(exc).__name__)


_singleton = None; _lock = threading.Lock()
def get_calibration_registry():
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None: _singleton = CalibrationRegistry()
    return _singleton
