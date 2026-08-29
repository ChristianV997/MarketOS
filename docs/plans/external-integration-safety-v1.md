# Plan: External integration safety (dry-run default)

Status: active
Lane: grok/marketos-external-integration-safety-v1
Owner: backend/integrations + evaluation/companyos (existing registry and governor)

## Goal

Prove that MarketOS external integrations remain safely disabled by default so later provider evaluation can proceed without accidental live calls.

This is not a provider activation plan.

## Defect reproduced

`backend.integrations.meta_ads_client.get_ad_spend` ignored `_is_dry_run()` / `_live()` and attempted a live Graph insights call whenever module-level credentials and the SDK were present. Create/pause/budget helpers already honored dry-run; spend read-back did not.

Shopify `get_orders` had no dry-run flag. Credentials plus an installed SDK were enough to leave the mock path.

## Change

- Route `get_ad_spend` through `_live()`.
- Add `SHOPIFY_DRY_RUN` (default `true`) so Shopify session activation stays fail-closed.
- Add focused tests for missing/malformed credentials, log redaction, default and explicit dry-run, blocked unapproved spend/live action, duplicate registration, and a deterministic safety report.
- Document the operator contract. Do not add a second provider registry or governor.

## Out of scope

Event contracts, workspace isolation, frontend, scripts/ai, runtime packaging, unit economics, reporting, CoderOS, browser automation, advertising activation, payments, live commerce.

## Validation

- `python -m pytest tests/test_external_integration_safety.py tests/test_resource_execution_governor.py tests/test_companyos_provider_registry.py tests/test_meta_ads_client.py -q`
- `python -m compileall backend/integrations/shopify_client.py backend/integrations/meta_ads_client.py tests/test_external_integration_safety.py`
- `ruff check` on touched files when available
- `git diff --check`
