# Commercial Intelligence Engine v1

MarketOS commercial intelligence is a deterministic domain layer over persisted local, manual, and cached evidence. It is separate from orchestration: it extracts evidence features, interprets market/category signals, analyzes product hypotheses, and records confidence and limitations.

Creative drafts derived from these reports are covered by [Creative Intelligence](CREATIVE_INTELLIGENCE.md); they remain substantiation-gated hypotheses.

## Market intelligence

Market reports distinguish demand and trend proxies from competition and saturation risk. They also summarize price, supplier, creative, customer, and seasonality signals when those signals are present. Attractiveness is a bounded planning score, not market size, sales, profit, ROI, or demand.

## Product intelligence

Product reports combine category context with product-level evidence when available. They score demand fit, differentiation, margin plausibility, supplier plausibility, competition risk, creative potential, and validation readiness separately. Positioning, bundle, upsell, variant, creative, and validation ideas are explicitly hypotheses. Failure modes and missing evidence are always surfaced.

## Confidence and limitations

Confidence falls with missing signal coverage, low-confidence rows, synthetic fixtures, and limited source diversity. Synthetic evidence is never treated as real market data. A commercial intelligence report is advisory and cannot bypass opportunity gates or authorize a launch candidate.

## Integration

Reports are persisted in `state/commercial_intelligence_registry.json`, exposed through `/api/commercial-intelligence`, and can be linked into knowledge graph snapshots, strategic priorities, optimization actions, validation sprint context, and Product Validation Sprint deliverables. These integrations remain advisory and evidence-constrained.

## Example workflow

1. Import approved local/manual evidence.
2. Run `/api/commercial-intelligence/market/analyze` for a category.
3. Run `/api/commercial-intelligence/product/analyze` for a hypothesis.
4. Review confidence, missing evidence, failure modes, and recommended imports.
5. Refresh refinement, opportunity pipeline, validation sprint, deliverable, and executive intelligence artifacts.

## Safety

No live web/API data, scraping, provider login, external writes, customer contact, commerce mutation, or arbitrary code execution is used. Evidence quality remains dependent on the local/cached inputs supplied to MarketOS.
