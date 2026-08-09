"""Hostinger HostingProvider adapter — read-only status/plan-usage boundary.

Implements the new backend.contracts.adapters.HostingProvider Protocol.
MarketOS does not provision or de-provision hosting; this adapter only
reads account/VPS status for cost-plan comparison purposes. Endpoint paths
follow Hostinger's published VPS API shape at authoring time — verify
against current Hostinger API docs before relying on this in production;
degrades to an "unconfigured" result with zero credentials, never fails
hard.
"""
from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

from backend.contracts.adapters import AdapterHealth, HostingProvider

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None


class HostingerHostingAdapter:
    name = "hostinger"

    def __init__(self, api_token: str | None = None, *, base_url: str | None = None,
                 timeout_s: float = 10.0, client: Any = None):
        self.api_token = api_token or os.getenv("HOSTINGER_API_TOKEN", "")
        self.base_url = (base_url or os.getenv("HOSTINGER_BASE_URL", "https://developers.hostinger.com/api")).rstrip("/")
        self.timeout_s = timeout_s
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self.api_token)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self.configured:
            return {"source": "unconfigured"}
        if httpx is None and self._client is None:
            return {"source": "unconfigured", "detail": "httpx is required for the Hostinger adapter"}
        client = self._client or httpx.Client(base_url=self.base_url, timeout=self.timeout_s,
                                               headers={"Authorization": f"Bearer {self.api_token}"})
        response = client.request(method, path, **kwargs)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {"data": payload}

    def health(self) -> AdapterHealth:
        if not self.configured:
            return AdapterHealth(self.name, configured=False, reachable=False,
                                  detail="HOSTINGER_API_TOKEN is unset")
        result = self._request("GET", "/vps/v1/virtual-machines")
        reachable = result.get("source") != "unconfigured"
        return AdapterHealth(self.name, configured=True, reachable=reachable,
                              capabilities=("hosting_status",) if reachable else ())

    def get_status(self) -> Mapping[str, Any]:
        return self._request("GET", "/vps/v1/virtual-machines")

    def list_sites(self) -> Sequence[Mapping[str, Any]]:
        result = self._request("GET", "/vps/v1/virtual-machines")
        if result.get("source") == "unconfigured":
            return [result]
        data = result.get("data", result)
        return data if isinstance(data, list) else [data]

    def get_plan_usage(self) -> Mapping[str, Any]:
        return self._request("GET", "/billing/v1/subscriptions")


hosting_provider_hostinger: HostingProvider = HostingerHostingAdapter()
