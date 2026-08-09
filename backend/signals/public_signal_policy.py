"""Explicit capability policy for manual, no-auth public signal reads."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .public_sources import MAX_RECORDS, RSS_SOURCE, RSS_URL_TEMPLATE


@dataclass(frozen=True)
class PublicSourcePolicy:
    source: str
    endpoint_template: str
    requires_credentials: bool
    allows_network_read: bool
    requires_explicit_network_opt_in: bool
    supports_cache: bool
    supports_stale_fallback: bool
    maximum_records: int
    allowed_actions: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    safety_notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PublicIngestionGuard:
    allowed: bool
    status: str
    reasons: list[str] = field(default_factory=list)
    normalized_query: str = ""
    normalized_limit: int = 0
    requires_network_opt_in: bool = True
    policy: PublicSourcePolicy | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["policy"] = self.policy.to_dict() if self.policy else None
        return data


def public_rss_policy() -> PublicSourcePolicy:
    return PublicSourcePolicy(
        source=RSS_SOURCE,
        endpoint_template=RSS_URL_TEMPLATE,
        requires_credentials=False,
        allows_network_read=True,
        requires_explicit_network_opt_in=True,
        supports_cache=True,
        supports_stale_fallback=True,
        maximum_records=MAX_RECORDS,
        allowed_actions=("read_public_only", "cache_local_observation", "append_advisory_canonical_event"),
        forbidden_actions=(
            "write_source", "publish", "spend", "mutate", "login", "credentialed_fetch",
            "browser_automation", "pagination", "provider_action", "launch",
        ),
        safety_notes=(
            "Manual invocation only; no scheduler is registered.",
            "Network use requires explicit CLI or caller opt-in.",
            "Observed RSS coverage is advisory evidence, never commerce authority.",
        ),
    )


def validate_public_ingestion_request(
    source: str,
    query: str,
    limit: int,
    *,
    allow_network: bool,
    fixture_mode: bool,
) -> PublicIngestionGuard:
    """Validate bounded public-read intent without performing I/O."""
    policy = public_rss_policy()
    reasons: list[str] = []
    if source not in {"rss", RSS_SOURCE}:
        reasons.append("unsupported_public_source")
    normalized_query = " ".join(str(query or "").split()).strip()
    if not normalized_query:
        reasons.append("query_required")
    try:
        normalized_limit = int(limit)
    except (TypeError, ValueError):
        normalized_limit = 0
        reasons.append("limit_must_be_integer")
    if normalized_limit < 1:
        reasons.append("limit_must_be_positive")
    if normalized_limit > policy.maximum_records:
        reasons.append(f"limit_exceeds_maximum:{policy.maximum_records}")
    if not fixture_mode and not allow_network:
        reasons.append("network_opt_in_required")
    if fixture_mode and allow_network:
        reasons.append("fixture_mode_does_not_require_network")
    status = "ready" if not reasons else "blocked"
    return PublicIngestionGuard(
        allowed=not reasons,
        status=status,
        reasons=reasons,
        normalized_query=normalized_query,
        normalized_limit=min(max(normalized_limit, 1), policy.maximum_records) if normalized_limit else 0,
        requires_network_opt_in=not fixture_mode,
        policy=policy,
    )


def public_source_capabilities() -> list[dict[str, Any]]:
    """A compact readiness-compatible list without modifying legacy readiness."""
    policy = public_rss_policy()
    return [{
        "name": policy.source,
        "status": "ready",
        "reason": "public_no_auth_manual_invocation",
        "requires_credentials": policy.requires_credentials,
        "network_required": True,
        "configured": True,
        "allowed_actions": list(policy.allowed_actions),
        "forbidden_actions": list(policy.forbidden_actions),
        "supports_cache": policy.supports_cache,
        "supports_stale_fallback": policy.supports_stale_fallback,
    }]
