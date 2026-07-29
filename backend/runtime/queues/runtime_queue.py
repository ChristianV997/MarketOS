from collections import deque


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
