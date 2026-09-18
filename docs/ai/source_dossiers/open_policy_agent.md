# Bounded Source Dossier: Open Policy Agent (OPA)

## Repository Identification
- **Repository URL**: `https://github.com/open-policy-agent/opa`
- **Pinned Commit SHA**: `b2c26708e9d55645d7f837db495031f7e4152594`
- **Pinned Release / Tag**: `v1.20.2`
- **License**: `Apache-2.0`

## License & Attribution Obligations
- **Attribution Obligations**: Retain Apache-2.0 notice and copyright.
- **Dependency & License Risks**: Permissive license. Go binary or Wasm compile target; running as sidecar introduces deployment complexity.

## Technical Profile
- **Security & Advisory Status**: Clean. CNCF graduated project.
- **Supported Runtimes**: Go, WebAssembly.
- **Tests & Maturity**: Industry standard declarative policy engine.
- **Data & Network Behavior**: In-memory evaluation of Rego policies against JSON inputs; optional HTTP server daemon.

## MarketOS Integration Seam & Disposition
- **Intended MarketOS Seam**: `evaluation.trustos.policy_gate (declarative input/output policy and gate verification).`
- **Adoption Decision**: `emulate`
- **Vendor / Wrap / Study Classification**: `studied (policy grammar emulated; do not run external Go daemon).`
- **Rollback / Deactivation Strategy**: Python procedural assertion gates.
- **Operator Approval Requirement**: None for native python rule engine.
