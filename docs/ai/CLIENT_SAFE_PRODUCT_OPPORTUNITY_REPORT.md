# Client-Safe Product Opportunity Report

`services.client_safe_product_opportunity_report` is a route-neutral adapter
for client-facing review of the existing offline discovery path. It does not
rank candidates or calculate economics.

## Callable path

```python
from services.client_safe_product_opportunity_report import (
    build_client_safe_product_opportunity_report,
)

report = build_client_safe_product_opportunity_report(
    "evaluate",
    sanitized_discovery_payload,
    workspace=resolved_server_workspace,
    registry=workspace_registry,
)
json_body = report.to_dict()
markdown_body = report.markdown
```

The `workspace` argument must be an existing `ClientWorkspace` resolved by a
server-side identity/membership boundary, and `registry` must be the existing
`WorkspaceRegistry`. A payload `workspace_id` is checked for consistency but
never selects a workspace.

## Projection contract

The report preserves canonical candidate order and identity, evidence
references grouped as marketplace, supplier, and consumer-attention metadata,
evidence class, freshness as an evidence-age label, blockers, conflicts,
unknowns, assumptions, and per-currency boundaries. Missing amounts remain
missing; explicit zero values remain explicit values. Currency conversion is
never inferred or performed.

The export envelope is produced only by
`evaluation.trustos.client_workspace_isolation.export_client_evidence` and
uses its existing metadata allowlist. The projection excludes raw reports,
prompts, formulas, heuristics, source code, raw provider payloads,
credentials, filesystem paths, and cross-workspace data. It is deterministic,
bounded, offline, read-only, and not evidence of supplier verification, legal
clearance, launch readiness, spend approval, publishing, outreach, orders,
payments, or live validation.
