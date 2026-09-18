# Bounded Source Dossier: Prefect

## Repository Identification
- **Repository URL**: `https://github.com/PrefectHQ/prefect`
- **Pinned Commit SHA**: `c8986edebb2dde3e2a931adbe24d2eaefcb799cb`
- **Pinned Release / Tag**: `3.2.0`
- **License**: `Apache-2.0`

## License & Attribution Obligations
- **Attribution Obligations**: Retain Apache-2.0 notice and copyright.
- **Dependency & License Risks**: Permissive license, but massive dependency tree (FastAPI, aiohttp, rich, typer, pydantic v2 core).

## Technical Profile
- **Security & Advisory Status**: Clean.
- **Supported Runtimes**: Python 3.9 - 3.13.
- **Tests & Maturity**: Widely adopted Python orchestration framework.
- **Data & Network Behavior**: Client-server API communication with Prefect Server or Prefect Cloud.

## MarketOS Integration Seam & Disposition
- **Intended MarketOS Seam**: `backend.execution.task_states (explicit state transitions: PENDING, RUNNING, COMPLETED, FAILED).`
- **Adoption Decision**: `reject`
- **Vendor / Wrap / Study Classification**: `studied (rejected orchestrator duplication; single event spine rule; emulate task transition states only).`
- **Rollback / Deactivation Strategy**: Native Python enums for execution state.
- **Operator Approval Requirement**: None for state enum reference.
