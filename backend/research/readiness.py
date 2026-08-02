"""Non-invasive readiness and evidence policy for scheduled research sources."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from backend.research.credentials import CredentialLoadStatus, credential_status


@dataclass(frozen=True)
class ResearchSourceSpec:
    name: str
    flag_env: str
    credential_env: tuple[str, ...] = ()
    real_only: bool = True
    evidence_mode: str = "live"


SOURCE_SPECS: tuple[ResearchSourceSpec, ...] = (
    ResearchSourceSpec("google_trends_v1", "FF_RESEARCH_SOURCE_GOOGLE_TRENDS_V1"),
    ResearchSourceSpec("reddit", "FF_RESEARCH_SOURCE_REDDIT"),
    ResearchSourceSpec("mercadolibre", "FF_RESEARCH_SOURCE_MERCADOLIBRE"),
    ResearchSourceSpec("youtube_trends", "FF_RESEARCH_SOURCE_YOUTUBE"),
    ResearchSourceSpec("amazon_bestsellers", "FF_RESEARCH_SOURCE_AMAZON_BESTSELLERS"),
    ResearchSourceSpec(
        "tiktok_organic",
        "FF_RESEARCH_SOURCE_TIKTOK_ORGANIC",
        credential_env=("TIKTOK_ACCESS_TOKEN", "TIKTOK_ADVERTISER_ID"),
    ),
)

_SPECS_BY_NAME = {spec.name: spec for spec in SOURCE_SPECS}


def _enabled(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _global_enabled() -> bool:
    if "FF_PILLAR_A_INGESTION" in os.environ:
        return _enabled("FF_PILLAR_A_INGESTION")
    return _enabled("FF_PILLAR_A_SOURCE_V1")


def _spec_for(name: str) -> ResearchSourceSpec | None:
    return _SPECS_BY_NAME.get(name)


def source_readiness(
    name: str,
    *,
    global_enabled: bool | None = None,
    credentials: CredentialLoadStatus | None = None,
    summary: Mapping[str, Any] | None = None,
    reliability: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    spec = _spec_for(name)
    if spec is None:
        return {
            "name": name,
            "status": "ready",
            "reason": "custom_adapter",
            "enabled": True,
            "real_only": True,
            "evidence_mode": "live",
        }
    global_flag = _global_enabled() if global_enabled is None else global_enabled
    source_flag = _enabled(spec.flag_env, default=_enabled("FF_PILLAR_A_SOURCE_V1") if name == "google_trends_v1" else False)
    missing = [key for key in spec.credential_env if not os.getenv(key, "").strip()]
    status = "ready"
    reason = "configured"
    if not global_flag:
        status, reason = "disabled", "global_flag_disabled"
    elif not source_flag:
        status, reason = "disabled", "source_flag_disabled"
    elif missing:
        status, reason = "missing_credentials", "required_credentials_missing"
    elif credentials is not None and credentials.configured and not credentials.loaded:
        status, reason = "degraded", "credential_store_unavailable"
    item: dict[str, Any] = {
        "name": name,
        "flag_env": spec.flag_env,
        "enabled": status == "ready",
        "status": status,
        "reason": reason,
        "required_credentials": list(spec.credential_env),
        "missing_credentials": missing,
        "real_only": spec.real_only,
        "evidence_mode": spec.evidence_mode,
    }
    if summary:
        item.update({
            "record_count": int(summary.get("record_count", 0)),
            "topic_count": int(summary.get("topic_count", 0)),
            "confidence": summary.get("confidence"),
            "last_success_at": summary.get("freshness_ts"),
        })
    if reliability:
        item["reliability"] = dict(reliability)
    return item


def source_reliability(
    name: str,
    *,
    runs: list[Mapping[str, Any]] | None = None,
    summary: Mapping[str, Any] | None = None,
    required_runs: int = 3,
    minimum_records: int = 5,
    maximum_rejection_rate: float = 0.10,
    max_age_hours: float = 72.0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate the deterministic staging gate without performing a fetch."""
    now = now or datetime.now(timezone.utc)
    successful_runs: list[Mapping[str, Any]] = []
    for run in runs or []:
        payload = run.get("payload") or {}
        source = (payload.get("sources") or {}).get(name)
        if not isinstance(source, Mapping) or source.get("status") != "succeeded":
            break
        successful_runs.append(source)
    quality_checks = []
    for source in successful_runs[:required_runs]:
        fetched = max(0, int(source.get("fetched", 0) or 0))
        rejected = max(0, int(source.get("rejected", 0) or 0))
        rejection_rate = rejected / fetched if fetched else 1.0
        quality_checks.append({
            "minimum_records": fetched >= minimum_records,
            "rejection_rate": round(rejection_rate, 4),
            "rejection_rate_ok": rejection_rate < maximum_rejection_rate,
        })
    fresh = False
    freshness_ts = str((summary or {}).get("freshness_ts") or "")
    if freshness_ts:
        try:
            observed = datetime.fromisoformat(freshness_ts.replace("Z", "+00:00"))
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
            fresh = (now - observed.astimezone(timezone.utc)).total_seconds() <= max_age_hours * 3600
        except ValueError:
            fresh = False
    reliable = (
        len(successful_runs) >= required_runs
        and len(quality_checks) == required_runs
        and all(check["minimum_records"] and check["rejection_rate_ok"] for check in quality_checks)
        and int((summary or {}).get("record_count", 0) or 0) >= minimum_records
        and fresh
    )
    return {
        "reliable": reliable,
        "consecutive_successful_runs": len(successful_runs),
        "required_successful_runs": required_runs,
        "quality_checks": quality_checks,
        "fresh": fresh,
        "minimum_records": minimum_records,
        "maximum_rejection_rate": maximum_rejection_rate,
    }


def all_source_readiness(
    *,
    summaries: list[Mapping[str, Any]] | None = None,
    credentials: CredentialLoadStatus | None = None,
    runs: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    credential_state = credentials or credential_status()
    by_source = {str(item.get("source")): item for item in (summaries or [])}
    reliability_by_source = {
        spec.name: source_reliability(spec.name, runs=runs, summary=by_source.get(spec.name))
        for spec in SOURCE_SPECS
    }
    reliable_sources = [name for name, value in reliability_by_source.items() if value["reliable"]]
    return {
        "global_ingestion_enabled": _global_enabled(),
        "credential_store": credential_state.public_dict(),
        "sources": [
            source_readiness(
                spec.name,
                credentials=credential_state,
                summary=by_source.get(spec.name),
                reliability=reliability_by_source[spec.name],
            )
            for spec in SOURCE_SPECS
        ],
        "promotion": {
            "status": "ready" if len(reliable_sources) >= 2 else "pending_corroboration",
            "reliable_sources": reliable_sources,
            "required_reliable_sources": 2,
            "recommended_min_sources": 2,
        },
    }
