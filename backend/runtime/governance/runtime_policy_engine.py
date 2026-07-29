class RuntimePolicyEngine:
    def __init__(self):
        self.rules = {
            "max_queue_size": 1000,
            "allow_desktop_execution": True,
            "replay_required": True,
        }

    def validate(self, payload: dict):
        if self.rules["replay_required"] and not payload.get("replay_hash"):
            return {
                "valid": False,
                "reason": "missing replay hash",
            }

        return {
            "valid": True,
        }
