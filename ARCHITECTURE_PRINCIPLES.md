# MARKETOS ARCHITECTURE PRINCIPLES

The executable ownership and dependency rules live in
[`ARCHITECTURE_CONTRACT.md`](ARCHITECTURE_CONTRACT.md). This file remains a
short set of design principles, not a parallel specification.

## Deterministic First
Replay safety overrides convenience.

## One Event Spine
All systems emit canonical event envelopes.

## One Orchestration Layer
No parallel orchestrators.

## Semantic Memory
All cognition systems connect to shared memory.

## Observable Runtime
Everything emits telemetry.

## Revenue Optimization
The system compounds profitable decisions.

## Local First AI
Inference supports local execution.

## Replay Safety
All runtime actions must be reproducible.
