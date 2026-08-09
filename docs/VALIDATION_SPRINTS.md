# Validation Sprints

Validation sprints select `validation_ready` opportunities and run only audited deterministic services through the existing governed dry-run loop. Product research and customer-intelligence scaffolds are input-only; economics runs only when explicit product/offer inputs exist.

Each target produces a persistent scorecard with bounded score/confidence, completed or unavailable services, risks, missing evidence, and a cautious transition recommendation. `launch_candidate` remains a planning label and never authorizes ads, orders, payments, messaging, publishing, or commerce mutation.

Creative Intelligence can add advisory hooks, angles, proof requirements, and manual review hypotheses; it never launches an ad or changes a scorecard by itself.

Use: run discovery → refresh the opportunity pipeline → inspect `validation_ready` → POST `/api/discovery/validation-sprints` → review scorecards → refresh refinement for blockers. Sprint and scorecard artifacts are optionally written to Obsidian under `03_Experiments`.

For a client-ready paid-service output, generate the persisted package through `/api/deliverables/product-validation-sprint`; see [Product Validation Sprint Deliverables](PRODUCT_VALIDATION_SPRINT_DELIVERABLES.md).
# Workflow orchestration

Validation sprints can run as a checkpointed, synchronous stage through [WORKFLOW_ORCHESTRATOR.md](WORKFLOW_ORCHESTRATOR.md).
