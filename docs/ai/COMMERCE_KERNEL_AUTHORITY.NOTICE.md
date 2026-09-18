# NOTICE — PR #250 does not own the financial-evidence kernel

Owner of money arithmetic: PR #248 (`codex/marketos-profit-evidence-kernel-v1`,
HEAD `38b53a264bf9e1343b47161d2647149a5ab3918f`).

This branch is stacked on #248. The following files are inherited from that
parent and are intentionally absent from the #250-owned diff:

- `backend/economics/kernel.py` (blob `4baba4be5bcddeab71d841d0d8f26f84a7c8bef3`)
- `backend/economics/__init__.py` (blob `9458f2fb6eaa13cab6164a26c3764c5a219e08d9`)
- `docs/FINANCIAL_EVIDENCE_KERNEL.md` (blob `764dd8bb5dc889d1b6cfc3fb58cf7dae2e8ed62f`)

They are not a second authority. Do not edit them on this branch.

The #250-owned surface is:

- `evaluation/commerce/kernel_integration.py`
- `evaluation/commerce/canonical.py`
- `evaluation/commerce/business_model_economics.py`
- `evaluation/commerce/promotion.py`
- `evaluation/commerce/dry_run_lifecycle.py`
- `evaluation/commerce/dry_run_scenarios.py`
- `evaluation/companyos/service_engagement.py`
- `tests/commerce_canonical/*`
- `docs/ai/COMMERCE_KERNEL_INTEGRATION.md`

`tests/test_financial_economics_kernel.py` belongs to #248. The supplier-lane
adapter assertion in that file requires #248's `supplier_feasibility.py` edit
and must not be reintroduced here against `main`.

Merger next action: verify the #248 parent relationship, keep the unique
commerce files, then rebase #256 (`56810fc`) onto the new #250 HEAD. Do not
merge from this lane.
