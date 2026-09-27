# Consulting Offer Catalog

## Purpose

`services.consulting_offers` is a productized, offline catalog and proposal
adapter. It defines six bounded consulting offers and produces deterministic
proposal and statement-of-work drafts without creating a billing system, CRM,
payment flow, provider client, event spine, score, promotion gate, economics
calculator, or launch authority.

The output is useful for client scope review. It is not a quote, contract,
invoice, accounting opinion, supplier approval, legal conclusion, live market
validation, profit guarantee, launch authorization, or proof of a transaction.

## Offers

| ID | Offer | Existing package authority | Primary evidence boundary |
|---|---|---|---|
| `diagnostic-audit` | Diagnostic Audit | Product Validation Sprint | Objective, context, sources, blockers |
| `market-research-sprint` | Market-Research Sprint | Product Validation Sprint | Market and customer observations |
| `unit-service-economics` | Unit and Service Economics | Unit Economics + CAC/ROAS Diagnostic | Explicit cost, currency, and delivery inputs |
| `supplier-logistics-feasibility` | Supplier and Logistics Feasibility | Product Validation Sprint | Supplier, shipping, returns, and support evidence |
| `marketing-publicity-strategy` | Marketing and Publicity Strategy | Managed Marketing / CRO | Customer, claims, and creative evidence |
| `full-commercial-assessment` | Full Commercial Assessment | Composition of existing package bands | Cross-component provenance and blockers |

The offer IDs are client-facing compositions. Price ranges are calculated from
the existing `evaluation.companyos.service_catalog.ServicePackage` entries
through `catalog_with_canonical_services()` and `package_map()`. They retain
the package currency and `pricing_evidence_state="assumed"`; no new price
authority or currency conversion is introduced.

## Authority Graph

```text
ConsultingOfferRequest
  -> registered ClientWorkspace + WorkspaceRegistry
  -> caller-supplied, workspace-bound ArtifactStore.path_for (no write)
  -> existing CompanyOS ServicePackage price bands
  -> ReportRegistry references (workspace checked)
  -> typed evidence/state aggregation
  -> proposal draft + SOW draft (safe projections only)
  -> TrustOS export_client_evidence allowlist
  -> deterministic fingerprint + existing Markdown renderer
```

The builder requires the caller to provide the already-bound `ArtifactStore`.
It verifies that the store's workspace exactly matches the registered
`ClientWorkspace` before path validation. It never constructs a second store,
registers a workspace, writes a proposal, or resolves a raw workspace ID into
an authority.

Component reports are references only: report ID, service, status, workspace,
and experiment identity. Missing or cross-workspace reports are rejected.
Report findings, raw payloads, prompts, formulas, source code, credentials,
and internal professional packets never enter the client projection.

The related consulting-engagement PR is currently unmerged on `main`. This
catalog therefore accepts an optional `consulting_engagement_id` as a
reference-only lineage field in the internal proposal draft and does not import
or execute that branch. The reference is deliberately omitted from the
client-safe and TrustOS allowlisted projections. Once a compatible engagement
authority is merged, a caller may attach its registered ID without changing
this catalog's identity or export boundary.

## Evidence and Status

Evidence class and state remain distinct:

- `fixture`, `manual`, `manual_import`, `simulated`, `planned`, and `derived`
  remain planning evidence and never become live proof;
- `missing`, `stale`, `conflicting`, `blocked`, and `unavailable` produce
  deterministic blockers;
- no evidence produces `needs_evidence` rather than false readiness;
- an explicitly live, available, authoritative input may be summarized as
  `live_authoritative_evidence`, but launch authorization remains `false`;
- unknown offering kind blocks offer selection until classification is
  confirmed;
- a supplier listing is not supplier permission, a market observation is not
  demand proof, and a creative signal is not ad performance.

Proposal statuses are:

- `draft_ready`: supplied evidence is current enough for human scope review;
- `needs_evidence`: the diagnostic draft is usable, but required evidence is
  not supplied;
- `blocked`: conflicts, stale or missing evidence, unsupported offering
  applicability, currency mismatch, workspace mismatch, or scope blockers
  prevent review progression.

Every proposal includes exclusions, assumptions, turnaround, human review
points, required inputs, next action, and optional upgrade paths. These are
planning metadata; they do not authorize external work.

## Client-Safe Export

The full proposal retains safe offer definitions and planning price bands. The
TrustOS export is narrower and uses the existing allowlist only:

```text
workspace_id
status
blockers
evidence_required
approvals_required
next_actions
```

Export provenance is deterministic `derived://consulting-offers/<proposal-id>`
and evidence state is `requires_review`. The export is bounded, redacted, and
workspace-bound through `evaluation.trustos.client_workspace_isolation`.

## Determinism and Safety

Offer definitions are emitted in stable ID order. Proposal IDs and
fingerprints use the existing commerce replay fingerprint helper. Markdown
uses `services.reporting.render.render_markdown_report` with a fixed offline
timestamp and its mandatory dry-run disclaimer. Repeating a request produces
byte-equivalent JSON and Markdown.

Inputs reject control characters, secret-shaped values, raw payload markers,
internal prompt/formula/source markers, unsafe IDs, unsupported offer IDs,
invalid currencies, and malformed evidence. No credentials, client artifacts,
provider responses, network calls, database writes, orders, payments,
publishing, messaging, or ad actions are performed.

## Local Validation

```text
python scripts/ai/session_start.py --json
python scripts/ai/check_dev_stack.py --json
python scripts/ai/select_tests.py --from-git --json
python -m pytest -q tests/services/test_consulting_offers
python -m pytest -q tests/contracts/test_architecture_boundaries.py
python -m compileall -q backend api evaluation services scripts tests
python -m ruff check services/consulting_offers tests/services/test_consulting_offers
git diff --check
python scripts/ai/session_finish.py --dry-run
python scripts/ai/run_local_quality_gate.py --from-git --json
python scripts/ai/pr_readiness_report.py --json
```

These commands provide local or dry-run evidence only. GitHub Actions with no
runner-assigned executed steps are `ci_unavailable`, never a pass. Fixture and
manual evidence remain below live validation regardless of local test results.
