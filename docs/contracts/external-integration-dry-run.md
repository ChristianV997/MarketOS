# Dry-run safety contract (external integrations)

Normative for `backend/integrations/` clients used before provider evaluation.

1. Importing an integration module must not open a network connection.
2. Missing, empty, or malformed credentials must not enable a live path.
3. Dry-run is the default. Live requires an explicit `*_DRY_RUN=false` plus usable credentials plus an importable SDK.
4. Read helpers (`get_ad_spend`, `get_orders`) obey the same live predicate as mutation helpers.
5. Logs must not emit credential-shaped values.
6. CompanyOS `ProviderRegistry` remains the only provider registry. Duplicate registration is rejected or no-op with an explicit duplicate signal.
7. CompanyOS `resource_execution_governor` remains the only execution governor. Unapproved spend or live actions stay blocked or simulation-only.
8. Tests must fail closed if a patched network primitive is invoked.
9. Reports from this lane must not list providers as available or live-validated.
10. Future activation is gated by the Approval Ledger and is out of scope here.
