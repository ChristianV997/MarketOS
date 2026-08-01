"""Opt-in runtime benchmark for the Chatwoot ConversationProvider adapter.

Benchmarks `backend.integrations.chatwoot.ChatwootConversationAdapter`
against whatever real `CHATWOOT_BASE_URL`/`CHATWOOT_API_ACCESS_TOKEN`/
`CHATWOOT_ACCOUNT_ID` are configured. Read-only: only calls `health()`
(which itself only reads `GET /inboxes`) — every other adapter method
either creates a contact/conversation or is an explicit draft/handoff, so
there is no additional read-only listing method to probe here.
See scripts/_provider_benchmark.py for the shared harness.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from scripts._provider_benchmark import cli_main, run_adapter_benchmark
except ModuleNotFoundError:  # direct ``python scripts/evaluate_chatwoot_benchmark.py``
    from _provider_benchmark import cli_main, run_adapter_benchmark


def benchmark(execute: bool) -> dict[str, object]:
    from backend.integrations.chatwoot import ChatwootConversationAdapter

    return run_adapter_benchmark(
        candidate="chatwoot",
        reviewed_ref="pending-deferred-review",
        make_adapter=ChatwootConversationAdapter,
        execute=execute,
    )


def main() -> int:
    return cli_main(benchmark)


if __name__ == "__main__":
    raise SystemExit(main())
