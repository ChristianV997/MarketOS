"""Composable, deterministic Commerce MVP packet runner."""
from __future__ import annotations
import hashlib, json
from dataclasses import replace
from pathlib import Path
from typing import Any
from backend.creative_intelligence.claim_safety import sanitize_creative_claim
from backend.events.repository import EventRepository
from backend.providers.vendor_router import recommend_vendor_for_capability
from backend.signals.public_signal_models import PublicSignal
from .approval_packet import build_manual_approval_packet
from .events import commerce_mvp_events
from .landing_page_packet import build_landing_page_packet
from .models import CommerceMvpRun, CreativePacket, OpportunityCandidate, UnitEconomicsSummary
from .opportunity import build_opportunity_candidates_from_signals, select_candidate
from .store_draft_packet import build_store_draft_packet


def _load_signals(path: str | Path) -> list[PublicSignal]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = value.get("signals", value) if isinstance(value, dict) else value
    return [PublicSignal.from_dict(item) for item in rows]


def _economics(candidate: OpportunityCandidate, price: float, unit_cost: float, shipping: float, cac: float, returns: float, payment_rate: float) -> UnitEconomicsSummary:
    fee = round(price * payment_rate, 2); retained = price * (1 - returns)
    gross = round(retained - unit_cost - shipping - fee, 2); contribution = round(gross - cac, 2)
    return UnitEconomicsSummary(candidate.candidate_id, price, unit_cost, shipping, fee, returns, cac, gross, contribution, gross,
        ("All inputs are dry-run assumptions; no actual margin, CAC, profitability, or ROAS conclusion is supported.",),
        (f"Assumed price={price}", f"Assumed unit cost={unit_cost}", f"Assumed shipping={shipping}", f"Assumed CAC={cac}", f"Assumed return rate={returns}"), "dry_run_assumption")


def _economics_with_evidence(candidate: OpportunityCandidate, price: float, assumed_unit_cost: float, assumed_shipping_cost: float,
                              cac: float, returns: float, payment_rate: float, *, evidence: Any) -> UnitEconomicsSummary:
    """Same math as _economics(), but prefers an observed supplier cost/
    shipping over the assumed defaults when supplier_evidence.py found one,
    and records which component was observed vs assumed. Additive only:
    _economics() itself is unchanged and remains what every existing caller
    (with evidence=None) gets."""
    has_cost = evidence is not None and evidence.unit_cost is not None
    has_shipping = evidence is not None and evidence.shipping_cost is not None
    unit_cost = evidence.unit_cost if has_cost else assumed_unit_cost
    shipping = evidence.shipping_cost if has_shipping else assumed_shipping_cost
    fee = round(price * payment_rate, 2); retained = price * (1 - returns)
    gross = round(retained - unit_cost - shipping - fee, 2); contribution = round(gross - cac, 2)
    cost_note = f"Observed CJ supplier cost={unit_cost} (source={evidence.source_url})" if has_cost else f"Assumed unit cost={unit_cost}"
    shipping_note = f"Observed CJ shipping={shipping} (source={evidence.source_url})" if has_shipping else f"Assumed shipping={shipping}"
    source = "partial_observed_supplier_evidence" if (has_cost or has_shipping) else "dry_run_assumption"
    warnings = ("Price, CAC, and return-rate inputs remain dry-run assumptions unless explicitly marked 'Observed' below; "
                "no actual margin, CAC, profitability, or ROAS conclusion is supported.",)
    return UnitEconomicsSummary(candidate.candidate_id, price, unit_cost, shipping, fee, returns, cac, gross, contribution, gross,
        warnings, (f"Assumed price={price}", cost_note, shipping_note, f"Assumed CAC={cac}", f"Assumed return rate={returns}"), source)


def _creative(candidate: OpportunityCandidate) -> CreativePacket:
    draft = f"Draft use-case angle: explore how {candidate.product_name} may fit a practical routine."
    safe = sanitize_creative_claim(draft, [{"signal_ids": candidate.evidence_signal_ids}])
    return CreativePacket(candidate.candidate_id, ("Practical use-case hypothesis", "Problem-awareness hypothesis"),
        (safe["safe_text"], "Draft hook: What would you verify before choosing this product?"),
        ("Creator instruction: demonstrate verified product details; do not claim personal experience unless genuine and approved.",),
        ("0–3s: show the product/use case", "3–10s: explain verified detail", "10–15s: invite review of verified information"),
        tuple(safe["limitations"]), tuple(safe["blocked_reasons"]), ("Use only verified specifications and approved product imagery.",),
        ("creatify", "heygen", "canva", "capcut"))


def _recommendations() -> tuple[dict[str, Any], ...]:
    capabilities = ("ecommerce_platform", "landing_page_builder", "video_ad_generation", "social_content_generation", "chat_support", "analytics", "error_tracking", "database_auth_storage", "backend_hosting", "frontend_hosting")
    return tuple(recommend_vendor_for_capability(item).to_dict() for item in capabilities)


def run_commerce_mvp_slice(*, workspace_id: str = "commerce-mvp-dry-run", query: str, signal_fixture_path: str | Path | None = None,
                           signals: list[PublicSignal] | None = None, mode: str = "fixture", max_signals: int = 10, max_candidates: int = 5,
                           assumed_price: float = 49.0, assumed_unit_cost: float = 15.0, assumed_shipping_cost: float = 6.0,
                           assumed_cac: float = 12.0, assumed_return_rate: float = .08, payment_fee_rate: float = .03,
                           write_repository: EventRepository | None = None, shopify_store_context: Any | None = None,
                           supplier_evidence: Any | None = None) -> CommerceMvpRun:
    rows = list(signals if signals is not None else _load_signals(signal_fixture_path) if signal_fixture_path else [])[:max(1, max_signals)]
    query = query.strip(); stable = hashlib.sha256((workspace_id + query + "|".join(item.signal_id for item in rows)).encode()).hexdigest()[:20]
    started = float(int(stable[:8], 16) % 1_000_000 + 1_700_000_000)
    candidates = build_opportunity_candidates_from_signals(rows, workspace_id, query, max_candidates)
    selected = select_candidate(candidates)
    warnings: list[str] = []
    if len(rows) < 2: warnings.append("thin_evidence: fewer than two public signals; do not advance without corroboration")
    if not selected: warnings.append("no_candidate_created: add attributed public-signal fixture data")
    # supplier_evidence defaults to None, so every existing caller gets the
    # exact same _economics() output as before this parameter existed.
    economics = (
        _economics_with_evidence(selected, assumed_price, assumed_unit_cost, assumed_shipping_cost, assumed_cac, assumed_return_rate, payment_fee_rate, evidence=supplier_evidence)
        if supplier_evidence is not None
        else _economics(selected, assumed_price, assumed_unit_cost, assumed_shipping_cost, assumed_cac, assumed_return_rate, payment_fee_rate)
    ) if selected else None
    creative = _creative(selected) if selected else None
    landing = build_landing_page_packet(selected) if selected else None
    store = build_store_draft_packet(selected) if selected else None
    recommendations = _recommendations()
    approval = build_manual_approval_packet(selected, recommendations) if selected else None
    base = CommerceMvpRun(f"commerce-mvp-{stable}", workspace_id, query, started, started, mode, "completed" if selected else "blocked", tuple(item.to_dict() for item in rows), tuple(candidates), selected, economics, creative, landing, store, recommendations, approval, (), tuple(warnings), ("manual_approval_required_before_external_action",), {"network_used": False, "provider_calls": False, "supabase_default": False, "jsonl_default": False})
    if shopify_store_context is not None:
        # Imported context is evidence only: the existing deterministic candidate
        # selection and economics remain untouched.
        from backend.ecommerce.shopify_readonly.enrichment import enrich_commerce_mvp_with_shopify_context
        base, _ = enrich_commerce_mvp_with_shopify_context(base, shopify_store_context)
    events = commerce_mvp_events(base)
    if write_repository is not None: write_repository.append_many(events)
    return replace(base, canonical_event_ids=tuple(event.event_id for event in events), completed_at=started + len(events) / 1000)

__all__ = ["run_commerce_mvp_slice"]
