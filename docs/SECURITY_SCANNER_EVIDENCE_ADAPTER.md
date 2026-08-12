# Security Scanner Evidence Adapter v1

MarketOS wraps scanner-shaped outputs; it does not become a scanner. The
adapter normalizes explicitly marked, sanitized fixture or uploaded-output
metadata into TrustOS evidence, risk items, and simulated gate impacts.

## Supported references

The registry covers Gitleaks, TruffleHog, GitHub secret scanning, CodeQL SARIF,
Semgrep JSON/SARIF, OSV-Scanner, Trivy, Syft, Grype, OpenSSF Scorecard,
OWASP Dependency-Check, ZAP baseline, Nuclei, PyRIT, garak, and manual review.
No tool is installed or executed by this version.

## Normalization and redaction

Fixtures must set `fixture_mode: true`. SARIF runs, direct findings, SBOM
package metadata, scorecard summaries, and manual review checks are reduced to
bounded findings with scanner ID, category, severity, title, summary, rule and
location placeholders. Raw reports, vulnerable source, exploit payloads, HTML,
cookies, credentials, tokens, and client data are rejected or summarized away.

The normalized records feed the existing TrustOS Evidence Locker and use its
control, evidence, risk, and gate vocabulary. They do not create another
evidence store or gate engine.

## Gate impacts

Critical/high secret and code findings can hard-block public launch, provider
activation, and credential use. Critical dependency findings hard-block public
launch; high findings create a soft block. AI prompt-injection and approval
bypass findings hard-block live model/tool activation. Low repository posture
scores warn, and incomplete manual review requests a security-owner review.
These are readiness decisions, not security guarantees or legal conclusions.

## Future roadmap

The next safe step is CI-owned scanner execution with reviewed licenses, bounded
artifacts, a redaction check, and TrustOS evidence tests. Scanner execution,
GitHub API access, live services, and public launch remain disabled by default.

## Commands

```text
python scripts/run_security_scanner_adapter.py --json
python scripts/run_security_scanner_adapter.py --scanner gitleaks --markdown
python scripts/run_security_scanner_adapter.py --fixture tests/fixtures/security_scanner_adapter/gitleaks_report_fixture.json --json
python scripts/run_security_scanner_adapter.py --action public_beta_launch --markdown
python scripts/run_security_scanner_adapter.py --run-local-scanner --json  # fails closed
```

Output files are written only when `--output` is supplied. This adapter makes no
network calls, reads no credentials, runs no scanners, stores no raw scanner
outputs, and performs no external action.
