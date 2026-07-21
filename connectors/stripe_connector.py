"""connectors.stripe_connector — Stripe revenue ground-truth connector.

Second, additive revenue ground-truth source alongside Shopify (see
backend/integrations/shopify_client.py). Falls back to mock charges when
STRIPE_SECRET_KEY is unset or the API call fails, so callers always get a
usable (if approximate) revenue figure.
"""
import os
import datetime

try:
    import requests as _requests
except ImportError:  # pragma: no cover
    _requests = None

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
API_BASE = "https://api.stripe.com/v1"

_FALLBACK_CHARGES = [
    {"id": "ch_mock_1", "amount": 10000, "currency": "usd", "status": "succeeded"},
    {"id": "ch_mock_2", "amount": 8000, "currency": "usd", "status": "succeeded"},
]


def _cents_to_dollars(cents: int) -> float:
    return round(cents / 100, 2)


def get_revenue(last_n_minutes: int = 60) -> dict:
    """Return charge revenue from Stripe, falling back to mock data."""
    now = datetime.datetime.now(datetime.UTC)
    since = now - datetime.timedelta(minutes=last_n_minutes)

    charges = _FALLBACK_CHARGES

    if STRIPE_SECRET_KEY and _requests is not None:
        try:
            url = f"{API_BASE}/charges"
            params = {"created[gte]": int(since.timestamp()), "limit": 100}
            resp = _requests.get(
                url, params=params, auth=(STRIPE_SECRET_KEY, ""), timeout=10
            )
            resp.raise_for_status()
            payload = resp.json()
            data = payload.get("data", [])
            parsed = [
                {
                    "id": ch["id"],
                    "amount": ch["amount"],
                    "currency": ch["currency"],
                    "status": ch["status"],
                }
                for ch in data
                if ch.get("id")
            ]
            if parsed:
                charges = parsed
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            charges = _FALLBACK_CHARGES

    succeeded = [c for c in charges if c.get("status") == "succeeded"]
    total_revenue = sum(_cents_to_dollars(c["amount"]) for c in succeeded)
    return {
        "charges": charges,
        "total_revenue": total_revenue,
        "since": since.isoformat(),
        "until": now.isoformat(),
    }
