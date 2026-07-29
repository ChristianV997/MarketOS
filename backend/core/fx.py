"""backend.core.fx — explicit currency handling for capital/budget figures.

Every budget_daily/capital figure elsewhere in this codebase flows straight
to ad platforms that bill in whatever currency the ad account is actually
configured in (assumed USD everywhere — e.g. backend.commerce.checkout
hardcodes "usd"). Before this module, no FX conversion existed anywhere in
production code; scripts/run_full_stack_simulation.py had to hand-roll an
18.5 MXN/USD conversion just to model a non-USD starting capital.

CAPITAL_CURRENCY makes that assumption explicit instead of implicit: it
declares what currency an operator-supplied capital figure (INITIAL_CAPITAL,
see backend.core.state.DEFAULT_CAPITAL) is denominated in, and to_usd()
converts it once at that entry point — preventing an ~18x accidental
overspend if someone funds the system in MXN thinking the platforms
already account for it.
"""
from __future__ import annotations

import os

# Static reference rates (units of currency per 1 USD) — deliberately not
# live-fetched: an external FX-rate API dependency for a figure that only
# matters at startup/config time is a failure mode not worth adding. Update
# these when rates drift meaningfully enough to matter.
_STATIC_RATES_PER_USD = {
    "USD": 1.0,
    "MXN": 18.50,
    "EUR": 0.92,
    "GBP": 0.79,
}


def capital_currency() -> str:
    """The currency an operator-supplied capital/budget figure is
    denominated in. Defaults to USD (no behavior change from before this
    module existed) — set CAPITAL_CURRENCY to declare otherwise."""
    return os.getenv("CAPITAL_CURRENCY", "USD").upper()


def to_usd(amount: float, currency: str | None = None) -> float:
    """Convert *amount* from *currency* (defaulting to capital_currency())
    to USD — the currency every ad-platform integration in this codebase
    assumes budgets are already denominated in."""
    resolved = (currency or capital_currency()).upper()
    rate = _STATIC_RATES_PER_USD.get(resolved)
    if rate is None:
        raise ValueError(f"unknown currency: {resolved}")
    return round(amount / rate, 2)
