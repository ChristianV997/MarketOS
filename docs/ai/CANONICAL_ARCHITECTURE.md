# Canonical Architecture

Updated: 2026-07-31
Scope: MarketOS agent-assisted development context.

Source of truth: executable code, tests, and current deployment configuration. This file is a compact index, not a second architecture document.

Inspect first: `orchestrator/`, `backend/`, `core/`, `signals/`, `evaluation/`, and `tests/`.

Current shape: signals and research feed normalized commerce/evaluation contracts; decision and validation logic applies economics and safety gates; commerce and launch adapters perform approved external actions; metrics and signal-cache telemetry feed feedback and learning.

Avoid duplicating orchestration, provider clients, risk gates, commerce contracts, or telemetry. Search callers before adding a subsystem.
