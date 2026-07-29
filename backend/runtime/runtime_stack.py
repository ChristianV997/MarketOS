from collections import deque
from datetime import datetime
from pathlib import Path
import hashlib
import json
import platform
import psutil
import subprocess


class RuntimePolicyEngine:
    def __init__(self):
        self.rules = {
            'max_queue_size': 1000,
            'allow_desktop_execution': True,
            'replay_required': True,
        }

    def validate(self, payload: dict):
        if self.rules['replay_required'] and not payload.get('replay_hash'):
            return {
                'valid': False,
                'reason': 'missing replay hash',
            }

        return {
            'valid': True,
        }


class RuntimeQueue:
    def __init__(self):
        self.queue = deque()

    def enqueue(self, payload):
        self.queue.append(payload)

    def dequeue(self):
        if not self.queue:
            return None

        return self.queue.popleft()

    def size(self):
        return len(self.queue)


class RuntimeAuditLog:
    def __init__(self):
        self.entries = []

    def record(self, actor: str, action: str):
        self.entries.append(
            {
                'timestamp': datetime.utcnow().isoformat(),
                'actor': actor,
                'action': action,
            }
        )

    def snapshot(self):
        return self.entries


class CommandSandbox:
    SAFE_COMMANDS = [
        'echo',
        'ls',
        'pwd',
    ]

    def execute(self, command: str):
        parts = command.split()

        if parts[0] not in self.SAFE_COMMANDS:
            return {
                'success': False,
                'error': 'command blocked',
            }

        result = subprocess.run(
            parts,
            capture_output=True,
            text=True,
        )

        return {
            'success': True,
            'stdout': result.stdout,
        }


class ReplayExporter:
    def export(self, replay_id: str, payload: dict):
        output = Path('exports')
        output.mkdir(exist_ok=True)

        target = output / f'{replay_id}.json'

        target.write_text(
            json.dumps(payload, indent=2)
        )

        return str(target)


class SemanticMemory:
    def __init__(self):
        self.records = []

    def append(self, memory: dict):
        self.records.append(memory)

    def recall(self, memory_type: str):
        return [
            record
            for record in self.records
            if record.get('type') == memory_type
        ]


class CreativeEmbeddingEngine:
    def embed(self, content: str):
        digest = hashlib.sha256(
            content.encode(),
        ).hexdigest()

        return {
            'vector_stub': digest[:32],
        }


class RuntimeHealth:
    def snapshot(self):
        return {
            'platform': platform.system(),
            'cpu_percent': psutil.cpu_percent(),
            'memory_percent': psutil.virtual_memory().percent,
        }


class AutonomousCommerceLoop:
    def execute(self, products):
        ranked = sorted(
            products,
            key=lambda x: x.get('velocity', 0),
            reverse=True,
        )

        outputs = []

        for product in ranked[:5]:
            outputs.append(
                {
                    'product': product,
                    'creative': {
                        'hooks': [
                            f"viral {product['name']}",
                            f"why everyone buys {product['name']}",
                        ],
                        'cta': 'shop now',
                    },
                }
            )

        return outputs
