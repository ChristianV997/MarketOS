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
        self.path = Path(path or os.getenv("MARKETOS_CALIBRATION_STATE", "state/source_calibration_registry.json"))
        self.signals = {}; self.profiles = {}; self.runs = {}
        self._lock = threading.RLock(); self.last_save_ok = True; self.load_failed = False
        self.load()
    def _writable(self):
        """Retry a failed read before any write, so a file that became readable is picked up without a restart."""
        if self.load_failed: self.load()
        return not self.load_failed
    def _put_profile(self, profile, *, replace_key=True):
        key = (profile.workspace_id, profile.source_name, profile.parser_type)
        if replace_key:
            for pid in [pid for pid, item in self.profiles.items() if pid != profile.profile_id and (item.workspace_id, item.source_name, item.parser_type) == key]: del self.profiles[pid]
        self.profiles[profile.profile_id] = profile
    def register_signals(self, signals):
        with self._lock:
            if not self._writable(): self.last_save_ok = False; return signals
            for signal in signals: self.signals[signal.signal_id] = signal
            self.save(); return signals
    def register_profile(self, profile):
        with self._lock:
            if not self._writable(): self.last_save_ok = False; return profile
            self._put_profile(profile); self.save(); return profile
    def register_calibration_run(self, run):
        with self._lock:
            if not self._writable(): self.last_save_ok = False; return run
            self.runs[run.calibration_id] = run; self.save(); return run
    def record_run(self, signals, profiles, run, *, replace_workspace_profiles=False):
        """Persist one run in a single write, under the lock. A failed write rolls back every in-memory change.

        A workspace run replaces the workspace's profiles and current signals, so retired evidence cannot stay listed.
        """
        with self._lock:
            if not self._writable():
                run.metadata["persisted"] = False; self.last_save_ok = False; return False
            before = self.snapshot()
            if replace_workspace_profiles:
                for pid in [pid for pid, item in self.profiles.items() if item.workspace_id == run.workspace_id]: del self.profiles[pid]
                for sid in [sid for sid, item in self.signals.items() if item.workspace_id == run.workspace_id]: del self.signals[sid]
            for signal in signals: self.signals[signal.signal_id] = signal
            for profile in profiles: self._put_profile(profile)
            self.runs[run.calibration_id] = run
            run.metadata["persisted"] = True
            self.save()
            if not self.last_save_ok:
                self.restore(before)
                run.metadata["persisted"] = False
            return self.last_save_ok
    def clear_for_tests(self):
        with self._lock:
            self.signals.clear(); self.profiles.clear(); self.runs.clear(); self.save()
    def load(self):
        self.load_failed = False
        try:
            if not self.path.exists(): return
            payload = self.path.read_bytes()
        except OSError as exc:
            # A read error is not corruption: leave the file alone and refuse writes until a later read succeeds.
            self.load_failed = True; self.signals, self.profiles, self.runs = {}, {}, {}
            _log.warning("calibration registry unreadable; writes disabled until it can be read: %s", type(exc).__name__)
            return
        try:
            raw = json.loads(payload)
            signals = raw.get("signals", {}); profiles = raw.get("profiles", {}); runs = raw.get("runs", {})
            # Records written before attribution and policy versioning are not verifiable, so they stay out of every adjustment.
            for item in list(signals.values()) + [x for run in runs.values() for x in run.get("signals", [])]:
                if "attribution" not in item: item.update(attribution="legacy_unverified", exclusion_reason="legacy_unverified")
            for item in list(profiles.values()) + [x for run in runs.values() for x in run.get("profiles", [])]:
                if "policy_version" not in item: item.update(evidence_status="legacy_unverified", recommended_priority_adjustment=0.0, confidence_multiplier_adjustment=1.0)
            self.signals = {k: SourceUsefulnessSignal.from_dict(v) for k, v in signals.items()}; self.profiles = {k: SourceCalibrationProfile.from_dict(v) for k, v in profiles.items()}; self.runs = {k: CalibrationRun.from_dict(v) for k, v in runs.items()}
        except Exception as exc:
            # Corrupt content (including bytes that are not UTF-8): quarantine under a fresh number, never over an earlier copy.
            index = 1
            while self.path.with_name(f"{self.path.name}.unreadable-{index}").exists(): index += 1
            try: os.replace(self.path, self.path.with_name(f"{self.path.name}.unreadable-{index}"))
            except OSError: pass
            _log.warning("calibration registry corrupt; moved aside and starting empty: %s", type(exc).__name__)
            self.signals, self.profiles, self.runs = {}, {}, {}
    def save(self):
        if self.load_failed:
            self.last_save_ok = False; return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            temp.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")
            temp.replace(self.path)
            self.last_save_ok = True
        except Exception as exc:
            self.last_save_ok = False
            _log.warning("calibration registry save failed: %s", type(exc).__name__)


    def register_signal(self, signal): return self.register_signals([signal])[0]

    def list_signals(self, workspace_id=None, source_name=None, parser_type=None, signal_type=None, limit=100): return list(self.signals.values())[:max(0, min(int(limit), 1000))] if not any([workspace_id, source_name, parser_type, signal_type]) else [x for x in self.signals.values() if (workspace_id is None or x.workspace_id == workspace_id) and (source_name is None or x.source_name == source_name) and (parser_type is None or x.parser_type == parser_type) and (signal_type is None or x.signal_type == signal_type)][:max(0, min(int(limit), 1000))]

    def get_profile(self, source_name, parser_type=None, workspace_id=None):
        # Without a workspace there is no tenant to read from, so the answer is None rather than another workspace's profile.
        if workspace_id is None: return None
        for profile in self.profiles.values():
            if profile.source_name == source_name and (parser_type is None or profile.parser_type == parser_type) and profile.workspace_id == workspace_id: return profile
        return None

    def profiles_for_parser(self, workspace_id, parser_type):
        return sorted((x for x in self.profiles.values() if x.workspace_id == workspace_id and x.parser_type == parser_type), key=lambda x: (x.source_name, x.profile_id))

    def list_profiles(self, workspace_id=None, parser_type=None, limit=100): return [x for x in self.profiles.values() if (workspace_id is None or x.workspace_id == workspace_id) and (parser_type is None or x.parser_type == parser_type)][:max(0, min(int(limit), 500))]

    def get_calibration_run(self, calibration_id): return self.runs.get(calibration_id)

    def list_calibration_runs(self, workspace_id=None, limit=50): return list(reversed([x for x in self.runs.values() if workspace_id is None or x.workspace_id == workspace_id]))[:max(0, min(int(limit), 500))]

    def to_dict(self): return {"signals": {k: v.to_dict() for k, v in self.signals.items()}, "profiles": {k: v.to_dict() for k, v in self.profiles.items()}, "runs": {k: v.to_dict() for k, v in self.runs.items()}}

    def snapshot(self): return {"signals": dict(self.signals), "profiles": dict(self.profiles), "runs": dict(self.runs)}

    def restore(self, snapshot): self.signals, self.profiles, self.runs = dict(snapshot["signals"]), dict(snapshot["profiles"]), dict(snapshot["runs"])


_singleton = None; _lock = threading.Lock()
def get_calibration_registry():
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None: _singleton = CalibrationRegistry()
    return _singleton
