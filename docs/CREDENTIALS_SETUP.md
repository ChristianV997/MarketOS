# Credential Setup Guide

This guide walks through setting up sandboxed API credentials for testing and customer onboarding.

## Meta Ads

1. Create a **Meta Business Account** (or use existing test account)
2. Go to **Settings → Users and Permissions → System Users**
3. Create a new **System User** with "Ads Manager" role
4. Generate an **Access Token** (valid for 60 days, auto-refresh recommended)
5. Note your **Ad Account ID** (format: `act_1234567890`)

**Environment variables for testing:**
```bash
export META_ACCESS_TOKEN="your_system_user_token"
export META_AD_ACCOUNT_ID="act_1234567890"
export META_DRY_RUN="false"  # Enable live API calls
```

**Test command:**
```bash
META_DRY_RUN=false META_ACCESS_TOKEN=... META_AD_ACCOUNT_ID=... \
  python -m pytest tests/test_real_api_integration.py::test_meta_live_campaign_roundtrip -v
```

## TikTok Ads

1. Go to **TikTok Ads Manager** (ads.tiktok.com)
2. In **Settings → Access Control**, create an **API Access Token**
3. Note your **Advertiser ID** (visible in account settings)
4. Store token securely (valid 1 year by default)

**Environment variables for testing:**
```bash
export TIKTOK_ACCESS_TOKEN="your_api_token"
export TIKTOK_ADVERTISER_ID="your_advertiser_id"
export TIKTOK_DRY_RUN="false"
```

**Test command:**
```bash
TIKTOK_DRY_RUN=false TIKTOK_ACCESS_TOKEN=... TIKTOK_ADVERTISER_ID=... \
  python -m pytest tests/test_real_api_integration.py::test_tiktok_live_campaign_created -v
```

## Shopify

1. Create a **Shopify dev store** (free development environment)
2. Go to **Settings → Apps and integrations → Develop apps → Create an app**
3. Under **Admin API**, grant scopes for:
   - `write_products`, `read_products`
   - `write_fulfillments`, `read_fulfillments`
4. Copy your **Access Token** and **Store URL** (e.g., `mystore.myshopify.com`)

**Environment variables for testing:**
```bash
export SHOPIFY_STORE_URL="mystore.myshopify.com"
export SHOPIFY_API_KEY="your_access_token"
export SHOPIFY_DRY_RUN="false"
```

**Test command:**
```bash
SHOPIFY_DRY_RUN=false SHOPIFY_STORE_URL=... SHOPIFY_API_KEY=... \
  python -m pytest tests/test_real_api_integration.py::test_shopify_live_product_created -v
```

## Stripe (Optional)

For revenue tracking and payouts (not yet implemented):

1. Create **Stripe test account**
2. Copy your **Publishable Key** and **Secret Key** (test mode)
3. Add webhooks for `payment_intent.succeeded` events

```bash
export STRIPE_PUBLISHABLE_KEY="pk_test_..."
export STRIPE_SECRET_KEY="sk_test_..."
export STRIPE_WEBHOOK_SECRET="whsec_..."
```

## Production Credential Rotation

All tokens should:
- Be rotated every 90 days minimum
- Use secure vaults (AWS Secrets Manager, HashiCorp Vault, etc.)
- Never be committed to git (use `.env` or vault)
- Have minimal required scopes
- Be monitored for unexpected API calls

## Customer Onboarding

When a customer connects their accounts, we:
1. Request each credential (token, ID, keys)
2. Verify with a test API call (create paused campaign → verify ID format → delete)
3. Store encrypted (AES-256) with audit timestamp
4. Periodically test connectivity (detect expired/revoked tokens)
5. Alert if multiple consecutive failures

See `backend/credentials/manager.py` for implementation.
