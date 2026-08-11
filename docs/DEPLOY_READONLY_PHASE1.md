# Deploying Phase 1 Read-Only Validation

Deploy the backend to Railway (preferred) or Render with platform-managed
secrets only. Set `MARKETOS_SUPPLIER_PROVIDER=cj`,
`MARKETOS_SUPPLIER_AUTH_READONLY=1`, `CJ_EMAIL`, and `CJ_API_KEY` server-side.
Never put these values in Vercel, `VITE_*`, git, logs, or artifacts.

Before any live probe, run:

```powershell
python scripts/check_readonly_deployment_readiness.py --platform railway --json
python scripts/check_phase1_supplier_readonly_access.py --provider cj --json
```

The API exposes `GET /api/deployment/readiness` and `GET /api/phase1/readiness`.
They report only boolean credential presence. Keep public commerce and Supabase
write gates at `0`; this deployment permits no supplier, Shopify, payment, ad,
fulfillment, or customer-message mutation.

Use the **Manual Read-Only Validation** GitHub workflow only after a human sets
repository secrets and deliberately selects its validation input. Rotate a
secret in the platform/GitHub secret store, then rerun preflight; no repository
change is required.
