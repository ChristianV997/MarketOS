# TrustOS Control Plane v1

TrustOS is MarketOS' common trust and readiness layer before public launch or
live provider activation. It does not add another approval engine, provider
registry, scanner, evidence engine, or professional-advice system. It applies
one reusable model across security, privacy, legal, tax, AI governance,
provider risk, financial controls, operations, launch readiness, and client
workspace safety.

## Control / Evidence / Gate / Exception

- **Control:** what must be true for a risky action or readiness claim.
- **Evidence:** a metadata record describing how the control is proved, its
  owner, freshness, redaction, and client visibility.
- **Gate:** the point at which the action is allowed, warned, soft-blocked,
  hard-blocked, or sent for professional review.
- **Exception:** a scoped request for a human, founder, lawyer, accountant, or
  security owner to review residual risk.

The Approval Ledger remains the canonical action approval system. TrustOS
reuses its request vocabulary and adds readiness evidence and professional
review context around it.

## Policy packs

The built-in packs are deterministic metadata:

- Security baseline: secret/dependency/code scans, supply chain, SBOM,
  incident contact, access review, rate limits, and audit logging.
- AI agent security: prompt injection, tool hijack, secret exfiltration,
  spend abuse, approval bypass, least privilege, and untrusted-input controls.
- Provider activation: provider/credential references, approval, budget,
  terms/privacy, output contract, raw-payload policy, and disabled live mode.
- Privacy/legal baseline: privacy and terms drafts, retention, cookie and
  identity disclosure, consent, DPA/vendor review, and professional review.
- Tax/accounting readiness: jurisdiction classification, SAT/CFDI, VAT OSS,
  GST/HST, US nexus, invoice, and accountant review placeholders.
- Public launch readiness: security, policy, incident, provider, approval,
  abuse/rate-limit, scorecard, and workspace-isolation evidence.
- Client-safe TrustOps: minimal exports, evidence checklist, risk register,
  professional packets, and cross-client isolation.

Framework names such as NIST CSF, CIS Controls, OWASP, NIST AI RMF, PyRIT,
garak, and OpenSSF Scorecard are references only. No scanner runs occur.

## Evidence Locker

The locker stores only evidence metadata. It tracks missing, draft, present,
stale, failed, passed, not-applicable, and review-required states, plus
expiry, redaction, owner, professional-review, and client-visible flags. It
does not copy scanner output, raw provider payloads, HTML, credentials, or
client documents by default.

## Gate Runner

`TrustGateRunner` and `evaluate_action()` simulate gates for provider calls,
credential use, messaging, model calls, publishing, ads, orders, payments,
accounting sync, personal data, uploads, public signup, beta launch, and
client exports. Missing approval, consent, privacy/terms, security evidence,
budget controls, isolation, or professional review produces a blocker or
review decision. No result performs the action.

## Public launch and client reports

Public launch readiness defaults to `blocked_for_public_beta` and
`blocked_for_live_provider_activation`. Internal dry-run planning remains
available. The client-safe report exposes only status, blockers, evidence,
approvals, next actions, and professional packets. It excludes internal
prompts, formulas, source code, heuristics, provider intelligence, and
cross-client learnings.

Lawyer-ready, accountant-ready, and security-reviewer packets are checklists,
not legal, tax, security, or compliance conclusions.

## Consulting opportunities

TrustOS supports a Public Launch Readiness Audit, SaaS Trust & Compliance
Setup, AI Agent Safety Audit, Ecommerce Compliance Readiness, Provider/Vendor
Risk Review, Monthly TrustOps Retainer, and Lawyer/Accountant-Ready Packet.
These are evidence and readiness services, not guarantees.

## Commands

```text
python scripts/run_trustos_control_plane.py --json
python scripts/run_trustos_control_plane.py --markdown
python scripts/run_trustos_control_plane.py --action activate_provider --markdown
python scripts/run_trustos_control_plane.py --action public_beta_launch --markdown
python scripts/run_trustos_control_plane.py --action client_workspace_export --markdown
python scripts/run_trustos_control_plane.py --client-safe --markdown
python scripts/run_trustos_control_plane.py --output artifacts/trustos/latest --markdown
```

## Safety boundaries

This version performs no network calls, scanner runs, credential reads,
provider/model calls, vector indexing, scraping, raw-payload storage, legal or
tax conclusions, publishing, advertising, orders, payments, messaging,
accounting mutations, or client-data processing. Future scanners and
professional review workflows require separate approval-gated integrations.

The Security Scanner Evidence Adapter extends TrustOS by normalizing sanitized
scanner-shaped fixtures into the existing Evidence Locker and gate vocabulary.
It does not run scanners or expose raw findings; see
`SECURITY_SCANNER_EVIDENCE_ADAPTER.md`.

Security CI Gate adds explicit, allowlisted, bounded local execution while
preserving the same fail-closed TrustOS boundary. Its default remains
plan/fixture-only; see `SECURITY_CI_GATE.md`.
