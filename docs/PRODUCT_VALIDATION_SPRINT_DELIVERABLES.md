# Product Validation Sprint Deliverables

This read-only package turns a persisted validation sprint into a client-ready Markdown and self-contained HTML report. It summarizes recorded opportunities, scorecards, evidence gaps, source IDs, risks, recommended imports, limitations, and next actions.

Generate it with `POST /api/deliverables/product-validation-sprint`. If no sprint exists, the result is blocked and directs the operator to run discovery, refresh the opportunity pipeline, and run a dry-run validation sprint. Artifacts are written under `state/deliverables`; Obsidian notes are optional.

The package does not claim demand, profitability, ROAS, or launch readiness without supporting evidence. `launch_candidate` remains a planning label. No ads, orders, payments, messaging, publishing, or commerce mutation occurs. Markdown/HTML can be converted to PDF manually later using an approved local document tool.

When present, Creative Intelligence sections are explicitly hypothesis-labeled and list missing proof rather than predicted creative performance.
# Workflow orchestration

Deliverable generation is available as a safe workflow stage through [WORKFLOW_ORCHESTRATOR.md](WORKFLOW_ORCHESTRATOR.md).
