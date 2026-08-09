# Opportunity Pipeline

MarketOS converts category discoveries and product hypotheses into persisted, evidence-linked opportunities. The pipeline is read-only and planning-oriented.

Stages are `discovered`, `evidence_requested`, `evidence_enriched`, `validation_ready`, `launch_candidate`, `rejected`, and `archived`. Gates require supplied evidence, not intuition: demand/trend, competition, and product cost/price evidence are checked before validation readiness. Governed reports are required before `launch_candidate`.

`launch_candidate` is not launch approval. It authorizes no ads, orders, payments, messaging, publishing, or commerce mutation. Every stage change is recorded as a transition with gate results and reasons.

Typical loop: run discovery → inspect opportunities → run refinement → import recommended local evidence → compare runs → calibrate sources → refresh the pipeline → review validation reports. Synthetic fixtures and cached evidence remain explicitly limited and cannot alone promote an opportunity to launch-candidate.

API endpoints are under `/api/discovery`: refresh, opportunity listing/detail, gate evaluation, manual gated transition, transition history, and pipeline snapshots.

Validation-ready opportunities can be summarized into a client-ready, evidence-constrained deliverable package after a dry-run sprint; see [Product Validation Sprint Deliverables](PRODUCT_VALIDATION_SPRINT_DELIVERABLES.md).
# Workflow orchestration

Pipeline refresh and validation can run through the checkpointed [WORKFLOW_ORCHESTRATOR.md](WORKFLOW_ORCHESTRATOR.md).
