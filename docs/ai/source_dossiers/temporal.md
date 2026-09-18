# Bounded Source Dossier: Temporal

## Repository Identification
- **Repository URL**: `https://github.com/temporalio/temporal`
- **Pinned Commit SHA**: `b16215104069f798b79592679d8a16dd3d702883`
- **Pinned Release / Tag**: `1.8.0`
- **License**: `BSL-1.1` (Server) / `MIT` (Python SDK)

## License & Attribution Obligations
- **Attribution Obligations**: Server is Business Source License 1.1 (non-OSI compliant, commercial production restrictions). Client SDK is MIT.
- **Dependency & License Risks**: BSL-1.1 server prevents unencumbered commercial embedding. Heavy distributed dependencies (Cassandra, PostgreSQL, gRPC server daemon).

## Technical Profile
- **Security & Advisory Status**: Clean, but requires cluster security, mTLS, and state persistence infrastructure.
- **Supported Runtimes**: Go (server), Python/TypeScript/Java/Go (SDKs).
- **Tests & Maturity**: Highly mature distributed durable execution engine.
- **Data & Network Behavior**: Distributed event history log over gRPC.

## MarketOS Integration Seam & Disposition
- **Intended MarketOS Seam**: `backend.observability.replay (deterministic span history inspired by Temporal activity logs).`
- **Adoption Decision**: `reject`
- **Vendor / Wrap / Study Classification**: `studied (rejected orchestrator duplication; MarketOS enforces a single native event spine; emulate replay history concepts only).`
- **Rollback / Deactivation Strategy**: Retain native MarketOS event spine and local state machines.
- **Operator Approval Requirement**: Mandatory review before any future distributed workflow engine consideration.
