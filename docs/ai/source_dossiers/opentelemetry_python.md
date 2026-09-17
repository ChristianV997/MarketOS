# Bounded Source Dossier: OpenTelemetry Python

## Repository Identification
- **Repository URL**: `https://github.com/open-telemetry/opentelemetry-python`
- **Pinned Commit SHA**: `5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f`
- **Pinned Release / Tag**: `v1.30.0`
- **License**: `Apache-2.0`

## License & Attribution Obligations
- **Attribution Obligations**: Retain Apache-2.0 notice and copyright.
- **Dependency & License Risks**: Permissive license. SDK package sprawl and contextvars overhead.

## Technical Profile
- **Security & Advisory Status**: Clean. CNCF standard.
- **Supported Runtimes**: Python 3.8 - 3.13.
- **Tests & Maturity**: De facto standard for distributed tracing and metrics.
- **Data & Network Behavior**: Tracing span generation in memory; network export via OTLP gRPC/HTTP if configured.

## MarketOS Integration Seam & Disposition
- **Intended MarketOS Seam**: `backend.observability.tracing (trace ID, span ID, baggage context propagation).`
- **Adoption Decision**: `adapt`
- **Vendor / Wrap / Study Classification**: `wrapped / adapt (context models adapted; exporters remain offline).`
- **Rollback / Deactivation Strategy**: Revert to standard Python logging formatters.
- **Operator Approval Requirement**: Live OTLP exporter network calls require operator approval.
