"""evaluation/source_governance/validator.py -- Fail-closed validation logic
for MarketOS source-adaptation registry and acceptance pipeline.

Enforces strict governance rules:
- Immutable revision (40-char hex commit SHA for git repos)
- Canonical license recognition & restrictive copyleft rejection (AGPL, ELv2, Sustainable Use)
- Raw credential & secret-shaped metadata rejection
- Inspected paths verification
- Network behavior documentation & unbounded network rejection
- Attribution requirement for copied patterns and integrated code
- Protection of canonical MarketOS authorities (TrustOS, Governor, Approval Ledger, Quality, Event Spine)
- Approved dependencies only (no unapproved heavy runtimes in core)
- Security surface verification (rejection of desktop-control and unverified IPC bridges)
- Freshness window enforcement
- Mandatory rollback deactivation strategy
- Verification evidence requirement
- Stale target-authority and synthetic-SHA interception via consolidation_rules
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional, Set

from .consolidation_rules import extra_record_errors
from .registry import (
    AdaptationMode,
    AdaptationWorkOrder,
    CompatibilityStatus,
    EvidenceBundle,
    IntegrationStatus,
    SourceAdaptationRecord,
    SourceAdaptationRegistry,
    TargetBoundaryReview,
)
