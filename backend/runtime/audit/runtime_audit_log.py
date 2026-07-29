from datetime import datetime


class RuntimeAuditLog:
    def __init__(self):
        self.entries = []

    def record(self, actor: str, action: str):
        self.entries.append(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "actor": actor,
                "action": action,
            }
        )

    def snapshot(self):
        return self.entries
