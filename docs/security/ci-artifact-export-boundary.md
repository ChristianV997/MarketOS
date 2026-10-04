# CI Artifact Export Boundary

Canonical reference for CI artifact handling and failure exporter governance in MarketOS.

## Security & Architectural Principles

1. **Explicit Producer Verification**:
   - Secondary workflows triggered by `workflow_run` execute in an independent, fresh runner environment.
   - Secondary workflows cannot access transient runtime state or unpersisted execution logs from a preceding run unless those artifacts were explicitly generated, packaged, and uploaded by an approved producer step in the triggering workflow.
   - Workflows must never attempt to export failure logs by copying source files or assuming runtime logs exist in a checked-out repository tree on a secondary runner.

2. **Removal of Unvetted Exporters**:
   - In the absence of an approved producer workflow with a strict, cryptographically verified artifact allowlist, ghost or pseudo-exporters (such as unvalidated `artifact_on_failure.yml` configurations) must be removed rather than uploading source checkouts or broad paths.

3. **Strict Path Allowlisting**:
   - All `actions/upload-artifact` invocations across CI must target bounded, explicit file paths or constrained build directories (e.g., `artifacts/semgrep-results.json`, `artifacts/pytest-results.json`, `dist/`).
   - Broad captures targeting repository root (`.`), system roots, parent directory hops (`..`), or unvetted directory structures are strictly forbidden.

4. **Least-Privilege Token Permissions**:
   - Every GitHub Actions workflow must explicitly declare a top-level or job-level `permissions` block constraining `GITHUB_TOKEN` scopes (typically `contents: read`).
   - No workflow may rely on default unconstrained repository write permissions.

5. **Action Version Governance**:
   - All GitHub Actions references must specify valid, verified action major versions or pinned SHA hashes.
