"""backend.adapters.research.meta_ad_library -- thin, fail-closed bridge from the
offline Meta Ad Library evidence contract in evaluation.commerce.meta_ad_library_evidence.

Dry-run (``SidecarContext.dry_run=True``, the default) normalizes a response shape the
caller supplies. Live mode (``dry_run=False``) never reaches the offline builder and never
opens a socket. It returns ``blocked_live_mode`` and names every prerequisite that is still
unmet. There is no live transport in this release.

This module reads no environment variables, loads no credentials, and imports no HTTP
client. The output is research context about public advertiser activity. It is not supplier
proof, not product demand, and grants no publishing, spend, or launch authority.
Ad evidence is deliberately not attached to ``ResearchCandidate.additional_evidence`` or
any scorer.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any

from backend.contracts.adapters import SidecarContext
from evaluation.commerce.meta_ad_library_evidence import (
    AdLibraryEvidenceReport,
    build_ad_library_evidence,
    make_report,
    validate_request,
)

_log = logging.getLogger(__name__)

# Every prerequisite a live request is missing today. Named explicitly, so a blocked result is never a bare refusal.
LIVE_PREREQUISITES = (
    "approved Approval Ledger request (approval_request_type=provider_call)",
    "developer identity verification and Meta app access (primary-source requirement, not verified here)",
    "primary-source verification of Ad Library API access, terms, and commercial research use",
    "geography coverage verified against primary documentation for the target country",
    "field availability verified against primary reference; spend, impression and targeting scope kept unavailable",
    "credential reference configured (credential-meta-ad-library, secret value absent)",
    "rate-limit policy and retry budget defined for a real transport",
    "monthly or per-run call budget approved",
    "privacy review of advertiser identity and creative excerpts complete",
    "output contract tests passing",
    "a separately reviewed live transport implementation",
)


def fetch_ad_library_evidence(
    search_terms: str,
    *,
    country: str,
    context: SidecarContext,
    response: Mapping[str, Any] | None = None,
    date_min: str | None = None,
    date_max: str | None = None,
    observed_at: float | None = None,
) -> AdLibraryEvidenceReport:
    """Return normalized ad-transparency evidence for one query, or a structured fail-closed result.

    ``response`` is a supplied fixture in the shape ``{"http_status": int, "body": {...}}``. It is
    required in dry-run mode, and it is ignored in live mode.
    """
    now = time.time() if observed_at is None else observed_at
    request_error = validate_request(search_terms, country, date_min, date_max, now)
    if request_error is not None:
        return make_report("invalid_request", search_terms="", country="", observed_at=0.0, blockers=(request_error,))
    if not context.dry_run:
        return make_report(
            "blocked_live_mode",
            search_terms="",
            country="",
            observed_at=now,
            blockers=("live_mode_requested",) + LIVE_PREREQUISITES,
            warnings=("Meta Ad Library live transport is not implemented in this release.",),
        )

    try:
        return build_ad_library_evidence(
            response,
            search_terms=search_terms,
            country=country,
            observed_at=now,
            date_min=date_min,
            date_max=date_max,
        )
    except Exception:
        # Fail closed. The exception text is never propagated: it could embed caller-supplied values.
        _log.warning("meta_ad_library_offline_builder_failed")
        return make_report(
            "malformed_response",
            search_terms="",
            country="",
            observed_at=now,
            blockers=("offline_builder_failed",),
            warnings=("Meta Ad Library offline builder failed unexpectedly; details withheld.",),
        )
