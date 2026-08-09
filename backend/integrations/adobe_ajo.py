"""Adobe Journey Optimizer (AJO) connector — backend integration (Priority 3).

The single Adobe AJO integration surface — a second, independent client
(connectors/adobe_ajo_connector.py) used to exist alongside this one,
authenticating with a bare bearer token (ADOBE_AJO_TOKEN) instead of AJO's
real OAuth 2.0 client-credentials flow. That connector's OAuth handling
(thread-safe token cache/refresh) is the more production-realistic of the
two, so it's what survives the merge — kept at this module path because
this is the one wired into backend/execution/loop.py's auto-kill/scale-up
path (with Tier 2 hardening already applied to that call site).

Wraps the AJO REST API to pause underperforming campaigns and scale budgets
for high-ROAS winners in real time.

Falls back to stub responses when credentials are absent so the execution
loop continues uninterrupted in offline / CI environments.

Environment variables:
  ADOBE_CLIENT_ID        OAuth 2.0 client_id (server-to-server credential)
  ADOBE_CLIENT_SECRET    OAuth 2.0 client_secret
  ADOBE_ORG_ID           IMS Organisation ID  (e.g. ABC123@AdobeOrg)
  ADOBE_SANDBOX_NAME     AJO sandbox name (default: ``prod``)
  ADOBE_IMS_URL          IMS token endpoint (default: Adobe production IMS)
"""
import datetime
import os
import threading

try:
    import requests as _requests
except ImportError:  # pragma: no cover
    _requests = None

CLIENT_ID = os.getenv("ADOBE_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("ADOBE_CLIENT_SECRET", "")
ORG_ID = os.getenv("ADOBE_ORG_ID", "")
SANDBOX_NAME = os.getenv("ADOBE_SANDBOX_NAME", "prod")
IMS_URL = os.getenv("ADOBE_IMS_URL", "https://ims-na1.adobelogin.com/ims/token/v3")

_AJO_BASE = "https://journey-optimizer.adobe.io/restapi/v1"

# Thread-safe token cache
_token_lock = threading.Lock()
_token_cache: dict = {"access_token": "", "expires_at": datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)}


def _is_configured() -> bool:
    return bool(CLIENT_ID and CLIENT_SECRET and ORG_ID and _requests is not None)


def _get_access_token() -> str:
    """Return a valid access token, refreshing via OAuth if needed (thread-safe)."""
    with _token_lock:
        now = datetime.datetime.now(datetime.timezone.utc)
        if _token_cache["access_token"] and now < _token_cache["expires_at"]:
            return _token_cache["access_token"]

        try:
            resp = _requests.post(
                IMS_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "scope": "openid,AdobeID,read_organizations",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            token = data.get("access_token", "")
            expires_in = int(data.get("expires_in", 3600))
            _token_cache["access_token"] = token
            _token_cache["expires_at"] = now + datetime.timedelta(seconds=expires_in - 60)
            return token
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            return ""


def _headers() -> dict:
    token = _get_access_token()
    return {
        "Authorization": f"Bearer {token}",
        "x-api-key": CLIENT_ID,
        "x-gw-ims-org-id": ORG_ID,
        "x-sandbox-name": SANDBOX_NAME,
        "Content-Type": "application/json",
    }


def _patch_campaign(campaign_id: str, payload: dict) -> dict:
    """PATCH a campaign object in AJO."""
    url = f"{_AJO_BASE}/campaigns/{campaign_id}"
    try:
        resp = _requests.patch(url, json=payload, headers=_headers(), timeout=15)
        resp.raise_for_status()
        return resp.json() if resp.content else {"status": "ok", "campaign_id": campaign_id}
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        return {"error": str(exc), "campaign_id": campaign_id}


def pause_campaign(campaign_id: str) -> dict:
    """Pause an AJO campaign by ID.

    Returns a result dict with ``status`` and ``campaign_id`` keys.
    Falls back to ``{"status": "paused_mock", ...}`` when credentials absent.
    """
    if not _is_configured():
        return {"status": "paused_mock", "campaign_id": campaign_id}

    result = _patch_campaign(campaign_id, {"status": "STOPPED"})
    result.setdefault("status", "paused")
    return result


def scale_campaign(campaign_id: str, budget_multiplier: float = 1.5) -> dict:
    """Scale up an AJO campaign's daily budget by *budget_multiplier*.

    Returns a result dict with ``status``, ``campaign_id``, and
    ``budget_multiplier`` keys.  Falls back to stub when credentials absent.
    """
    if not _is_configured():
        return {
            "status": "scaled_mock",
            "campaign_id": campaign_id,
            "budget_multiplier": budget_multiplier,
        }

    result = _patch_campaign(
        campaign_id, {"budgetMultiplier": round(float(budget_multiplier), 4)}
    )
    result.setdefault("status", "scaled")
    result["budget_multiplier"] = budget_multiplier
    return result


def apply_decision(campaign_id: str, action: str, budget_multiplier: float = 1.5) -> dict:
    """Route a high-level MarketOS action (``'pause'`` or ``'scale'``) to AJO.

    *action* — one of ``'pause'``, ``'scale'``, ``'hold'`` (no-op).
    Unknown actions are treated as hold.
    """
    if action == "pause":
        return pause_campaign(campaign_id)
    if action == "scale":
        return scale_campaign(campaign_id, budget_multiplier)
    return {"status": "hold", "campaign_id": campaign_id}


def is_configured() -> bool:
    """True when Adobe AJO credentials are present in the environment."""
    return _is_configured()
