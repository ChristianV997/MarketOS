# Consulting Client Delivery Pack

This package builds coherent consulting deliverables from internal reports securely.
It supports executive summaries, evidence matrices, assumptions, blockers, and recommendation elements.

## Security & Export Boundary
- It explicitly uses `evaluation.trustos.client_workspace_isolation.check_workspace_leakage`.
- Known internal fields like `internal_prompt` are scrubbed before validation.
- All credential-like outputs are rejected.
- Any mismatch in `workspace_id` between context and metadata is aborted with `cross_workspace_leakage`.

## Rendering
- Exposes `ConsultingDeliveryPackage.to_dict()` and `ConsultingDeliveryPackage.as_deliverable_package().to_markdown()`.
- Unfilled sections are gracefully handled and fall back to `"Awaiting complete report data."`.

## Authoritative Use
Do not implement a second export boundary. Re-use existing `DeliverablePackage` routines for downstream APIs.
