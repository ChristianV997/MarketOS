# Operator runbook: external integration dry-run

## Default posture

| Flag | Default | Live only when |
| --- | --- | --- |
| `META_DRY_RUN` | `true` | set to `false` **and** `META_ACCESS_TOKEN` + `META_AD_ACCOUNT_ID` present **and** facebook-business importable **and** Approval Ledger / governor allow the action |
| `SHOPIFY_DRY_RUN` | `true` | set to `false` **and** `SHOPIFY_STORE_URL` + `SHOPIFY_ACCESS_TOKEN` present **and** shopify SDK importable |

Absence of a flag means dry-run. `META_DRY_RUN=false` without credentials is still dry-run.

## Safe checks

1. Do not export live credentials into the process when running safety tests.
2. `python -m pytest tests/test_external_integration_safety.py -q`
3. Confirm the safety report fixture in that test lists `live_enabled: false`.
4. Treat any fixture spend or mock order totals as simulated. They are not live proof.

## Forbidden on this lane

Provider API calls, campaign publication, budget writes, checkout, order mutation, customer messages, credential persistence.

## Rollback

Revert the two client modules. Flags default closed, so rollback does not enable live mode.
