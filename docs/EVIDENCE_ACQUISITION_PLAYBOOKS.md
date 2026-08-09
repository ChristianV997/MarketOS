# Evidence Acquisition Playbooks

MarketOS uses manual and cache-first acquisition. Each acquisition plan explains which local export to prepare, the parser and schema, verification checks, and the confidence limits of the source. Connector stubs are documentation-only and disabled.

## Workflow

1. Run a refinement cycle.
2. Review acquisition plans and source playbooks.
3. Generate or inspect the matching template under `data/import_templates/`.
4. Fill it with an authorized local export and provenance.
5. Import through the cache-only discovery endpoint.
6. Compare discovery runs and repeat the gap analysis.

## Source limitations

- Google Trends supports directional trend proxies, not conversion or profit.
- TikTok observations support creative/trend proxies, not durable demand or profitability.
- Amazon rank supports a rank/competition proxy, not exact sales.
- Meta ad activity supports competition/creative observations, not demand or ROAS.
- Reddit supports audience language and pain-point proxies, not market size.
- MercadoLibre supports price/competition and explicitly supplied sold-count proxies.
- Supplier catalogs support cost, availability, shipping, and risk assumptions, not demand.
- Shopify and Stripe exports support first-party historical signals only.
- Generic CSV requires explicit signal type and provenance.

## Connector readiness

Every future connector must remain disabled until it has an audited read-only contract, scoped credentials if ever required, provenance-preserving output, rate limits, failure behavior, legal/source-policy review, and tests proving it cannot mutate commerce, advertising, payment, customer, or publishing systems.

No connector executes in the current phase. All current acquisition is manual export or local cache import.
