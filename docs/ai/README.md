# AI Development Workflow

This directory is the compact operating memory for Codex and Claude Code in MarketOS.

Start here:

1. Read [CANONICAL_ARCHITECTURE.md](CANONICAL_ARCHITECTURE.md) and [KNOWN_GAPS.md](KNOWN_GAPS.md).
2. Follow [TOOL_ROUTING_POLICY.md](TOOL_ROUTING_POLICY.md) for the smallest appropriate tool path.
3. Use [TOKEN_BUDGET_POLICY.md](TOKEN_BUDGET_POLICY.md) to keep context bounded.
4. Run `python scripts/ai/check_dev_stack.py` for environment readiness.
5. Generate a handoff with `python scripts/ai/generate_session_handoff.py --output docs/ai/SESSION_HANDOFF.md`.

The AI stack is optional workflow support. It must not become a second source of truth for application behavior, secrets, or source code. Update the canonical files after architecture or integration decisions, and keep session handoffs compact.

## Output reduction

Use `python scripts/ai/filter_test_output.py --input test.log` and `python scripts/ai/filter_semgrep_output.py --input semgrep.json` when handing diagnostics to an agent. These tools retain failures, actionable findings, and summaries while dropping routine noise.

Ollama and Obsidian remain optional. Their status is recorded in [OLLAMA_BENCHMARK.md](OLLAMA_BENCHMARK.md) and [OBSIDIAN_BRIDGE_STATUS.md](OBSIDIAN_BRIDGE_STATUS.md); neither is required for repository development.
