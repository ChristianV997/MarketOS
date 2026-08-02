"""Single-writer lease for PC/AWS research workers.

The local file lease is intentionally conservative: it prevents two workers
sharing a state directory from writing concurrently. A future S3/Dynamo
backend can implement the same interface without changing research code.
"""
from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path
from typing import Any


class ResearchLease:
    def __init__(self, path: str | Path = "state/research.lease", *, ttl_s: float = 900.0) -> None:
        self.path = Path(path)
        self.ttl_s = ttl_s
        self.owner = f"{socket.gethostname()}:{os.getpid()}"

    def acquire(self) -> bool:
        now = time.time()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                current = json.loads(self.path.read_text(encoding="utf-8"))
                if float(current.get("expires_at", 0)) > now and current.get("owner") != self.owner:
                    return False
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"owner": self.owner, "acquired_at": now, "expires_at": now + self.ttl_s}), encoding="utf-8")
            os.replace(tmp, self.path)
            return True
        except Exception:
            return False

    def heartbeat(self) -> bool:
        try:
            current = json.loads(self.path.read_text(encoding="utf-8"))
            if current.get("owner") != self.owner:
                return False
            current["expires_at"] = time.time() + self.ttl_s
            self.path.write_text(json.dumps(current), encoding="utf-8")
            return True
        except Exception:
            return False

    def release(self) -> bool:
        try:
            current = json.loads(self.path.read_text(encoding="utf-8"))
            if current.get("owner") == self.owner:
                self.path.unlink(missing_ok=True)
                return True
        except Exception:
            pass
        return False

    def status(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            value["active"] = float(value.get("expires_at", 0)) > time.time()
            return value
        except Exception:
            return {"active": False, "owner": "", "expires_at": 0}
