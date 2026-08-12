# Security CI Gate v1

Security CI Gate is the controlled execution layer between scanner evidence
normalization and TrustOS decisions. It is a small command policy, not a SOC,
SIEM, runtime monitor, or scanner orchestration platform.

## Default behavior

The default mode is `fixture_only`. It creates bounded plans and checks no
executables. `--plan-only` is also non-executing. Gitleaks, TruffleHog,
OSV-Scanner, and Trivy can run only when `--run-local-scanners` is explicitly
provided. CodeQL, Semgrep, Scorecard, and manual review are ingestion or plan
paths; this version does not configure or run them.

Missing binaries are reported as `skipped_unavailable`. Add
`--require-scanners` only when a local/CI environment intentionally requires a
selected binary; unavailable tools then fail closed.

## Allowlist and execution boundaries

Every command has a fixed executable name, bounded argument list, repository
scope, timeout, output cap, forbidden paths, and TrustOS control mapping. Calls
use an argument list with `shell=False`; no shell strings, unbounded globs,
uploads, credentials, network access, or artifact writes are allowed.

Scanner stdout/stderr is captured transiently, size-checked, decoded as JSON,
rejected if unsafe, and passed to the existing Security Scanner Evidence
Adapter. Raw streams are never printed or persisted. A timeout, unexpected
schema, secret-like field, raw HTML, exploit-like content, or output-cap breach
discards the result.

## TrustOS integration

Normalized findings become TrustOS evidence records and scanner gate impacts.
Critical secrets and dependencies can hard-block public launch and provider
activation. High dependencies soft-block. Missing scan evidence produces a
warning or soft block for high-risk actions. All decisions remain simulated;
the gate never publishes, sends, pays, orders, or activates a provider.

## Commands

```text
python scripts/run_security_ci_gate.py --json
python scripts/run_security_ci_gate.py --plan-only --markdown
python scripts/run_security_ci_gate.py --scanner gitleaks_detect --markdown
python scripts/run_security_ci_gate.py --fixture tests/fixtures/security_ci_gate/gitleaks_sanitized_output.json --markdown
python scripts/run_security_ci_gate.py --action public_beta_launch --markdown
python scripts/run_security_ci_gate.py --run-local-scanners --scanner gitleaks_detect --markdown
python scripts/run_security_ci_gate.py --run-local-scanners --require-scanners --scanner osv_scanner_lockfiles --json
python scripts/run_security_ci_gate.py --output artifacts/security_ci_gate/latest --markdown
```

With `--output`, only sanitized report, plan, availability, normalization,
TrustOS evidence/gate, and redaction files are written. Generated outputs must
not be committed.

## Future CI path

A future manually reviewed workflow may invoke `--plan-only` without secrets.
Actual scanner execution requires separate review of tool licenses, CI
ownership, retention, artifact handling, redaction, and TrustOS gate policy.

## Safety boundary

This version does not install scanners, call GitHub or external services, read
credentials, upload reports, persist raw scanner output, run CodeQL setup,
perform network access, or make external mutations.
