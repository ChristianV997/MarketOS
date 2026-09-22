# Marketing strategy workbench

Updated: 2026-09-22

Draft planning surface for a publicity strategy. It is not mounted in the operator router in this change.

## Boundary

Owned paths:

- `frontend/src/features/marketing-strategy-workbench/**`
- `frontend/tests/marketing-strategy-workbench*.test.mjs`
- this document

The module does not publish, spend, send messages, or call providers. Budget rows are assumptions. Claims without evidence render as needs review. Fixture, manual, simulated, unknown, stale, and assumption evidence keep visible labels.

Client-safe export omits internal-only briefs and rejects secret-shaped text. A successful export is still `draft_only` and `executed_campaign: false`.

Evidence for this change is fixture-tested composition, not live validation.
