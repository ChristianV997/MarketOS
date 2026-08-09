import os
import time
from collections import deque

# Entries only leave the buffer via get_ready(), filtered by a
# caller-supplied delay — if a consuming loop stalls or an outcome never
# matures, self.buffer previously grew without bound. This cap is a
# last-resort safety net (oldest-first eviction), not a substitute for the
# consuming loop actually calling get_ready() regularly.
_MAX_BUFFER_SIZE = int(os.getenv("DELAYED_REWARD_BUFFER_MAX", "5000"))


class DelayedRewardStore:

    def __init__(self):
        self.buffer: "deque[dict]" = deque(maxlen=_MAX_BUFFER_SIZE)

    def log(self, decision, outcome):
        self.buffer.append({
            "t": time.time(),
            "decision": decision,
            "outcome": outcome
        })

    def get_ready(self, delay):
        now = time.time()
        ready = [item for item in self.buffer if now - item["t"] >= delay]
        self.buffer = deque(
            (item for item in self.buffer if now - item["t"] < delay),
            maxlen=_MAX_BUFFER_SIZE,
        )
        return ready
