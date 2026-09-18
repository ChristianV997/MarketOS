# MarketOS Deployment Readiness Matrix

Status: Evidence snapshot for `origin/main` (`df59a0609897907c1565d7d5f78e20959095d430`) with deployment and security hardening lane `antigravity/marketos-deployment-auth-public-readiness-v2`.

> [!IMPORTANT]
> This document is an offline evidence and deployment classification matrix. It does NOT authorize live-provider execution, external publication, order placement, payments, or ad spend. All external actions remain simulation-only or dry-run by default.

---

## Classification Taxonomy

- **Evaluation Labels**: `works`, `simulated`, `unavailable`, `blocked`, `not_run`.
- **Readiness States**: `ready_local_dry_run`, `ready_isolated_worktree`, `not_ready_staging`, `not_ready_operator`, `not_ready_public`, `blocked_live`.

---

## 1. Local Dry-Run

- **Readiness State**: `ready_local_dry_run`
- **Classification**:
  - `works`: Offline validation scripts (`deployment_smoke_check.py --local`, `mvp_readiness.py`, `local_mvp_smoke.py`, `ingest_public_signals.py --fixtures`, `check_dev_stack.py`, `run_local_quality_gate.py --from-git`).
  - `works`: Dual health contract (`/health` public liveness, `/ready` preflight dependency verification).
  - `simulated`: Commerce MVP execution cycle with deterministic fixtures; CompanyOS and TrustOS policy packs.
- **Required Credentials**: None. Works completely offline with fixture data.
- **Implemented Controls**:
  - Local authentication fallback (`MARKETOS_AUTH_DISABLED=true` or unconfigured local mode logs non-fatal warning).
  - In-memory rate limiting and request ID tracking (`X-Request-ID`).
  - Local signal cache under `artifacts/public-signal-cache`.
- **Persistence**: File-based JSONL under `artifacts/` (e.g. `artifacts/commerce-mvp-live-events.jsonl`).
- **Rollback**: Terminate local process; wipe fixture outputs in `artifacts/`.
- **Cost**: $0.00.

---

## 2. Isolated Test Worktree

- **Readiness State**: `ready_isolated_worktree`
- **Classification**:
  - `works`: Isolated `git worktree add` workflows preventing pollution of canonical checkout.
  - `works`: Targeted test selection (`scripts/ai/select_tests.py --from-git`).
  - `works`: Clean git state checks before push/PR.
- **Required Credentials**: Local Git and GitHub CLI (`gh`) authentication for PR workflow.
- **Implemented Controls**:
  - Pre-commit hygiene checks (`git diff --check`, no staged artifacts or secrets).
  - Independent virtual environments or dependency checks.
  - Zero cross-talk with dirty canonical working trees.
- **Persistence**: Branch-local commits; untracked files deleted on worktree removal.
- **Rollback**: `git worktree remove --force <worktree_path>`.
- **Cost**: $0.00.

---

## 3. Private Staging Deployment

- **Readiness State**: `ready_private_staging` (Controlled operator-access staging only)
- **Classification**:
  - `works`: Dockerfile hardening: Python 3.12 (`FROM python:3.12-slim`), unprivileged user (`USER marketos`), healthcheck (`HEALTHCHECK` targeting `/health`), graceful shutdown signal (`STOPSIGNAL SIGINT`), immutable tags.
  - `works`: Production Compose hardening: `docker-compose.prod.yml` mandates `POSTGRES_PASSWORD`, eliminates dangerous host port binding (`5432:5432` removed), provisions container healthchecks (`pg_isready`, `redis-cli ping`), and enforces `restart: unless-stopped`.
  - `works`: Deployment manifests: Railway (`deploy/railway/railway.json`), Render (`deploy/render/render.yaml`), MVP environment contract (`deploy/mvp/env.contract.json`).
  - `works`: Fail-closed `/ready` endpoint rejecting deployments with unconfigured auth or insecure default passwords (`upos`, `postgres`, `admin`).
- **Required Credentials**:
  - Platform host environment (Railway/Render).
  - `MARKETOS_OPERATOR_TOKEN` or `MARKETOS_API_KEY` (required for staging administration).
  - Exact `ALLOWED_ORIGINS` (wildcards rejected in production mode).
  - Secure `POSTGRES_PASSWORD` (default `upos` strictly rejected).
- **Missing Controls / Blockers for Public Access**:
  - Tenancy isolation across multiple untrusted organizations.
  - Distributed rate limiting (currently in-memory per container instance).
- **Persistence**: Managed PostgreSQL / Redis or persistent volume `postgres_data`.
- **Rollback**: Revert to previous immutable image digest or Git SHA; unset staging environment variables.
- **Cost**: Low (bounded single-instance compute/database resources).

---

## 4. Authenticated Operator Deployment

- **Readiness State**: `ready_authenticated_operator` (Controlled single-tenant operator use)
- **Classification**:
  - `works`: Unified security middleware (`backend/security/auth.py`): Bearer token authentication, API key header authentication (`X-API-Key`), operator role enforcement (`operator` vs `client`).
  - `works`: Exact origin validation (`backend/security/cors.py`): strict origin matching, production wildcard ban.
  - `works`: Sensitive credential redaction and log masking (`backend/security/credentials.py`).
  - `works`: Webhook verification with replay protection (`backend/security/webhooks.py`).
  - `simulated`: Live action execution gate (`backend/security/live_action_gate.py`): all operations default to `dry_run=True`; live execution requires explicit confirmation flag, valid operator token, and Approval Ledger entry.
- **Required Credentials**:
  - Strong, high-entropy `MARKETOS_OPERATOR_TOKEN`.
  - Defined webhook secrets (`STRIPE_WEBHOOK_SECRET`, `SHOPIFY_WEBHOOK_SECRET`, etc.) if webhooks are received.
- **Persistence**: Server-side canonical event store under `artifacts/` or Supabase staging database.
- **Rollback**: Revoke operator token; restart backend service in read-only / dry-run mode.
- **Cost**: Low (controlled internal operator activity).

---

## 5. Public Client-Facing Deployment

- **Readiness State**: `not_ready_public`
- **Classification**:
  - `works`: Frontend client build configuration (Vercel with `VITE_API_BASE_URL`).
  - `works`: Client-facing draft safety: Launch Draft Pack outputs remain `status: draft`.
  - `blocked`: Multi-tenant workspace isolation across untrusted external clients (PR #211 / PR #231 boundaries must be merged).
  - `blocked`: Public anonymous access to commerce endpoints (`MARKETOS_PUBLIC_COMMERCE_RUNS` must remain `0`).
  - `blocked`: Distributed WAF and edge DDoS mitigation.
- **Required Credentials**: External identity provider / OAuth / multi-tenant client token registry.
- **Safety Rule**: Never deploy public client-facing services while multi-tenant isolation and edge rate limiting are incomplete.

---

## 6. Live Provider Activation (Suppliers, Payments, Ads, Publishing)

- **Readiness State**: `blocked_live`
- **Classification**:
  - `blocked`: Real payment processing (Stripe / PayPal live charge authority).
  - `blocked`: Live ad spend mutations (Meta Ads, TikTok Ads, Google Ads).
  - `blocked`: Automated supplier order creation (CJ Dropshipping, AliExpress, DSers live purchases).
  - `blocked`: Automated customer messaging and public storefront publishing.
- **Gate Authority**:
  - CompanyOS Approval Ledger is the canonical gate: live external actions remain simulation-only until a human-approved, evidence-backed policy exists.
  - `backend/security/live_action_gate.py` enforces fail-closed execution.
  - Environment variable `MARKETOS_ENABLE_LIVE_ACTIONS` defaults to `false`.

---

## Summary Matrix

| Environment Mode | Status | Auth Required | CORS Policy | Live Actions | DB / Storage |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Local Dry-Run** | `ready_local_dry_run` | Optional / Warn | Permissive / Localhost | Blocked (Dry-run) | JSONL (`artifacts/`) |
| **2. Isolated Worktree** | `ready_isolated_worktree` | None (Git only) | N/A | Blocked | Git / Branch local |
| **3. Private Staging** | `ready_private_staging` | Required | Exact Allowed Origins | Blocked (Dry-run) | Pinned Postgres/Redis |
| **4. Operator Deployment** | `ready_authenticated_operator` | Required (Token/Key) | Strict Exact Origins | Guarded / Ledger | Managed DB + JSONL |
| **5. Public Client-Facing** | `not_ready_public` | Tenancy Required | Strict Client Domain | Blocked | Multi-tenant Isolated |
| **6. Live Provider Activation**| `blocked_live` | Ledger Approval Gate | Strict | BLOCKED BY DEFAULT | Production Ledger |

---

## Hardening Implemented in This Lane

1. **Authentication & Authorization**:
   - Implemented `backend/security/auth.py` providing Bearer token and API key validation.
   - Distinct operator (`operator`) and client (`client`) roles with least-privilege scoping.
   - Fail-closed in production (`is_production_mode()` requires valid credentials).
2. **CORS Hardening**:
   - Implemented `backend/security/cors.py` requiring explicit exact origins in production.
   - Rejection of wildcard `*` origins and credentials-with-wildcard configurations.
3. **Webhook Integrity & Idempotency**:
   - Implemented `backend/security/webhooks.py` with HMAC-SHA256 signature verification for Stripe, Shopify, and CJ Dropshipping.
   - Timing-safe signature comparisons (`hmac.compare_digest`).
   - Timestamp verification and replay attack window protection.
4. **Live Mutation Protection Gate**:
   - Implemented `backend/security/live_action_gate.py` guarding orders, payments, ad spend, customer returns and credits, and publishing.
   - All mutations fail closed unless dry-run is explicitly disabled AND operator credentials AND approval tokens are verified.
5. **Credential Safety & Sanitization**:
   - Implemented `backend/security/credentials.py` preventing credential exposure in logs or JSON error payloads.
6. **Container & Compose Hardening**:
   - Pinned `Dockerfile` to `python:3.12-slim` (matching `.python-version`), non-root `USER marketos` (UID 10001, `/usr/sbin/nologin`), `HEALTHCHECK` on port 3000, `STOPSIGNAL SIGINT`, and Python environment variables (`PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1`, `PIP_DISABLE_PIP_VERSION_CHECK=1`).
   - Hardened `docker-compose.prod.yml`: unified on port 3000, removed host port exposure (`5432:5432` omitted), required `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in the environment}`, added container healthchecks for Postgres (`pg_isready`) and Redis (`redis-cli ping`), `redis:7-alpine`, `init: true`, and `stop_grace_period: 15s`.
   - Added database credential audit to `validate_production_deployment()` to reject default passwords (`upos`).
7. **Offline Reproducibility Harness**:
   - Integrated `scripts/run_high_value_path_harness.py` and `tests/test_high_value_path_harness.py` to deterministically benchmark high-value paths (unit economics, supplier import, competition normalization, report export, replay idempotency) without invoking live providers or mutation paths.
   - Preserved `docs/ai/DEV_DEPLOY_REPRODUCIBILITY.md` for clean offline replication guidelines.

---

## Deployment Collision Resolution & Canonical Authority

| Target Path | Colliding PRs | Canonical Owner | Retained Changes | Discarded / Harmonized Duplicate |
| :--- | :--- | :--- | :--- | :--- |
| `Dockerfile` | #249, #251, #258 | **PR #258** | Port 3000 standard, non-root user (UID 10001, `/usr/sbin/nologin`), Python runtime env vars, `/app/artifacts` dir, `STOPSIGNAL SIGINT`, healthcheck on `/health`. | Port 8000 deviation in earlier PR #258 drafts discarded; redundant layer ordering discarded. |
| `docker-compose.prod.yml` | #249, #251, #258 | **PR #258** | Port 3000 mapping, `redis:7-alpine`, `init: true`, `stop_grace_period: 15s`, container healthchecks, volume persistence `postgres_data`, private database networking (no 5432 host publish), fail-closed `POSTGRES_PASSWORD` env requirement. | Insecure fallback passwords (`POSTGRES_PASSWORD: upos`) discarded. |
| `tests/contracts/test_container_hardening.py` | #249, #258 | **PR #258** | Invariants for Python 3.12, non-root user, port 3000, stop signal, no `--reload`, compose no host publish, Render (`deploy/render/render.yaml`) and Railway (`deploy/railway/railway.json`) secret-free descriptor checks, Grafana invariants, deployment validator rejection of default passwords. | Divergent port 8000 assertions discarded. |
| `docs/DEPLOYMENT_READINESS_MATRIX.md` | #249, #258 | **PR #258** | Full 6-tier readiness matrix, evaluation taxonomy, implemented security controls, and cross-PR collision resolution table. | Partial staging-only matrix notes consolidated into canonical document. |
| `scripts/run_high_value_path_harness.py` | #249 | **PR #258** (Adopted) | Offline timing and fingerprint reproducibility harness for core paths; strict `live_actions: False`. | Adopted cleanly from PR #249 without alteration. |
| `tests/test_high_value_path_harness.py` | #249 | **PR #258** (Adopted) | Automated tests asserting deterministic unit economics, replay stability, and non-live invariants. | Adopted cleanly from PR #249 without alteration. |
| `docs/ai/DEV_DEPLOY_REPRODUCIBILITY.md` | #249 | **PR #258** (Adopted) | Operator instructions for worktree isolation, dev stack verification, and offline test selection. | Adopted cleanly from PR #249 without alteration. |
| `backend/security/*` | #251, #258 | **PR #258** | Canonical security suite (`auth.py`, `cors.py`, `credentials.py`, `live_action_gate.py`, `webhooks.py`, `deployment_validation.py`). | Fragmented security patches from closed PR #251 fully superseded. |
