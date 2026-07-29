import os
import random

from backend.decision.scoring import causal_score
from backend.decision.confidence import confidence_engine, apply_confidence
from backend.learning.signals import roas_velocity, roas_acceleration
from backend.learning.bandit_update import bandit_weight
from backend.learning.calibration import calibration_model
from backend.learning.score_normalization import (
    normalize_and_combine, record_decision_terms, get_scoring_stats
)
from backend.learning.contextual_bandit import product_bandit
from backend.regime.meta_strategy import strategy_memory
from backend.regime.confidence import regime_confidence
from backend.simulation.reality_gap import reality_gap_engine
from backend.core.state import ensure_state_shape
from backend.orchestration.event_store import event_store, new_workflow_id
from agents.world_model import world_model
from connectors.meta_ads_intel import MetaAdsIntel
from connectors.shopify_scraper import ShopifyScraper

_meta_intel = MetaAdsIntel()
_shopify_scraper = ShopifyScraper()

# Module-level caches to avoid per-decision network calls
_competition_cache: dict[str, float] = {}   # keyword → density score
_discovery_cache: list[dict] = []           # recently discovered Shopify products

_META_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
_SHOPIFY_STORE_URL = os.getenv("SHOPIFY_STORE_URL", "")

# Phase 4: chance-corrected floor for regime-confidence down-weighting.
# regime_confidence.confidence() is a hit-rate over a 4-way label space
# (growth/decay/volatile/stable), so a detector that's merely guessing
# scores well above 0 — anchoring the floor at the chance rate and
# linearly rescaling [floor, 1.0] -> [0, 1] means a detector no better
# than chance contributes nothing to the score, while a perfect one gets
# full trust (same logic as chance-corrected agreement statistics).
REGIME_CONF_FLOOR = 0.25


def _refresh_competition(keyword: str) -> float:
    """Return a competition density score for *keyword* (0–1, cached)."""
    if keyword in _competition_cache:
        return _competition_cache[keyword]

    if not _META_TOKEN:
        _competition_cache[keyword] = 0.5  # neutral fallback
        return 0.5

    try:
        score = _meta_intel.competition_score(keyword, _META_TOKEN)
        density = float(score.get("density", 0.5))
    except Exception:
        density = 0.5

    _competition_cache[keyword] = density
    return density


def _refresh_products() -> list[dict]:
    """Return recently discovered products from Shopify (cached per session)."""
    global _discovery_cache
    if _discovery_cache:
        return _discovery_cache

    if not _SHOPIFY_STORE_URL:
        return []

    try:
        _discovery_cache = _shopify_scraper.fetch_products(_SHOPIFY_STORE_URL)
    except Exception:
        _discovery_cache = []

    return _discovery_cache


def _interval_confidence(preds: dict) -> float:
    widths = [preds.get(f"width_{h}", 0.6) for h in ("6h", "12h", "24h")]
    mean_width = sum(widths) / len(widths)
    return 1.0 / (1.0 + mean_width)


def decide(state):
    state = ensure_state_shape(state)
    world_model.train(state.event_log)

    history = [r.get("roas", 0) for r in state.event_log.rows[-10:]]
    vel = roas_velocity(history)
    acc = roas_acceleration(history)

    # reality-gap + calibration composite confidence (smoothed EMA)
    gap_summary = reality_gap_engine.summary()
    cal_stats = calibration_model.stats()
    system_conf = confidence_engine.compute(
        reality_gap=gap_summary.get("reality_gap"),
        calibration_error=cal_stats.get("bias"),
    )

    transition = state.transition or {}
    transition_occurred = bool(transition.get("occurred"))
    transition_cooldown = max(0, state.transition_cooldown)

    # Enrich available variants with discovered Shopify products
    products = _refresh_products()
    product_variants = list(range(1, 6))  # default variants 1-5
    if products:
        # map top product titles to variant slots for scoring diversity
        product_variants = list(range(1, len(products) + 2))[:5]

    decisions = []

    # Phase 3 shadow mode: SCORING_NORMALIZE_LIVE (default false)
    normalize_live = os.getenv("SCORING_NORMALIZE_LIVE", "false").lower() == "true"

    for i in range(5):
        variant = product_variants[i % len(product_variants)]
        action = {"variant": variant}

        # use product title as competition keyword when available for meaningful scoring
        if products and i < len(products):
            keyword = str(products[i].get("title", variant))
            product_id = str(products[i].get("id", variant))
            category = str(products[i].get("category", "unknown"))
        else:
            keyword = str(variant)
            product_id = str(variant)
            category = "unknown"

        # competition penalty: high density → lower score for this variant
        competition_density = _refresh_competition(keyword)
        competition_penalty = competition_density * 0.2  # scale to ≤ 0.2

        preds = world_model.predict(action)

        weighted_pred = (
            0.5 * preds["roas_6h"] +
            0.3 * preds["roas_12h"] +
            0.2 * preds["roas_24h"]
        )

        corrected_pred = calibration_model.adjust_prediction(weighted_pred)

        c_score = causal_score(action, state.graph)
        velocity_bonus = vel + acc
        bandit_w = bandit_weight(action, state.graph)

        # Phase 3 follow-up: blend in the per-product LinUCB contextual
        # bandit's UCB score (real exploration/exploitation over historical
        # per-product ROAS, not just the graph-based bandit_weight stub).
        # Shadow-gated: journaled every cycle, only affects the score when
        # PRODUCT_BANDIT_LIVE=true.
        try:
            pb_score = product_bandit.score(product_id, category=category)
        except Exception:
            pb_score = 0.0
        product_bandit_live = os.getenv("PRODUCT_BANDIT_LIVE", "false").lower() == "true"
        bandit_w_used = (bandit_w + pb_score) if product_bandit_live else bandit_w

        regime_bonus = strategy_memory.score(state.detected_regime)

        # Phase 4: down-weight regime_bonus by the detector's own historical
        # hit-rate, so a chronically-wrong regime detector no longer gets
        # full trust in the score. Chance-corrected linear rescaling: f=0 at
        # or below chance accuracy, f=1 at perfect accuracy.
        regime_conf = regime_confidence.confidence()
        regime_conf_f = max(0.0, min(1.0, (regime_conf - REGIME_CONF_FLOOR) / (1.0 - REGIME_CONF_FLOOR)))
        regime_bonus_adjusted = regime_bonus * regime_conf_f
        regime_conf_live = os.getenv("REGIME_CONFIDENCE_WEIGHTING_LIVE", "false").lower() == "true"
        regime_bonus_used = regime_bonus_adjusted if regime_conf_live else regime_bonus

        # three-factor confidence: calibration × interval narrowness × system health
        calib_conf = calibration_model.confidence_weight()
        interval_conf = _interval_confidence(preds)
        confidence = calib_conf * interval_conf * system_conf

        # ─ Unnormalized score (legacy)
        legacy_score = corrected_pred + c_score + velocity_bonus + bandit_w_used + regime_bonus_used - competition_penalty

        # ─ Normalized score (Phase 3)
        raw_terms = {
            "corrected_pred": corrected_pred,
            "c_score": c_score,
            "velocity_bonus": velocity_bonus,
            "bandit_w": bandit_w_used,
            "regime_bonus": regime_bonus_used,
            "competition_penalty": competition_penalty,
        }
        record_decision_terms(raw_terms)

        # Compute precision weight: 1/width² normalized to [0, 1]
        pred_width = preds.get("width_6h", 0.5)
        precision_weight = 1.0 / (1.0 + pred_width)

        normalized_score = normalize_and_combine(raw_terms, confidence=precision_weight)

        # Choose score based on flag
        final_score = normalized_score if normalize_live else legacy_score

        # Shadow-mode journaling (fixed Phase 4: event_store.append() requires
        # (workflow_id, event, ...) positional args — the Phase 3 call below
        # silently threw inside its own try/except and never journaled).
        try:
            if not normalize_live:
                event_store.append(
                    new_workflow_id("decision"), "shadow_decision_scoring",
                    workflow="decision_engine", step="decide",
                    data={
                        "product_id": product_id,
                        "legacy_score": round(legacy_score, 4),
                        "normalized_score": round(normalized_score, 4),
                        "terms": {k: round(v, 4) for k, v in raw_terms.items()},
                        "confidence": round(confidence, 4),
                        "live": False,
                    },
                )
        except Exception:
            pass  # don't break decision if journaling fails

        try:
            event_store.append(
                new_workflow_id("regimeconf"), "shadow_regime_confidence_weighting",
                workflow="decision_engine", step="decide",
                data={
                    "product_id": product_id,
                    "detected_regime": state.detected_regime,
                    "regime_bonus_raw": round(regime_bonus, 4),
                    "regime_confidence": round(regime_conf, 4),
                    "f": round(regime_conf_f, 4),
                    "regime_bonus_adjusted": round(regime_bonus_adjusted, 4),
                    "live": regime_conf_live,
                },
            )
        except Exception:
            pass  # don't break decisions if journaling fails

        try:
            event_store.append(
                new_workflow_id("productbandit"), "shadow_product_bandit_weighting",
                workflow="decision_engine", step="decide",
                data={
                    "product_id": product_id,
                    "category": category,
                    "bandit_w_stub": round(bandit_w, 4),
                    "pb_score": round(pb_score, 4),
                    "bandit_w_used": round(bandit_w_used, 4),
                    "live": product_bandit_live,
                },
            )
        except Exception:
            pass  # don't break decisions if journaling fails

        decision_row = {
            "action":              action,
            "product_name":        keyword,
            "category":            category,
            "score":               final_score,
            "pred":                corrected_pred,
            "pred_lo":             round(0.5 * preds["lo_6h"] + 0.3 * preds["lo_12h"] + 0.2 * preds["lo_24h"], 4),
            "pred_hi":             round(0.5 * preds["hi_6h"] + 0.3 * preds["hi_12h"] + 0.2 * preds["hi_24h"], 4),
            "pred_width":          round(0.5 * preds["width_6h"] + 0.3 * preds["width_12h"] + 0.2 * preds["width_24h"], 4),
            "interval_conf":       round(interval_conf, 4),
            "system_conf":         round(system_conf, 4),
            "competition_density": round(competition_density, 4),
        }
        decisions.append(
            apply_confidence(
                decision_row,
                confidence,
                transition=transition_occurred,
                cooldown=transition_cooldown,
            )
        )

    decisions.sort(key=lambda x: x["score"], reverse=True)
    return decisions
