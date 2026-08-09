"""backend.patterns.errors — structured error taxonomy for MarketOS.

Bare ``except Exception: pass`` (or debug-log-and-swallow) hides the
difference between "this is fine, we have a fallback" and "this is a real
bug that will keep failing." This module gives call sites a small
vocabulary to raise instead:

  - RetryableError   — transient (timeout, 429, 5xx); caller may retry
  - ConfigurationError — missing/invalid credentials or setup; not retryable
  - SupplierQuoteError — supplier API failed or timed out (retryable)
  - ValidationError   — bad input data; not retryable, caller's fault

All inherit from MarketOSError so a single ``except MarketOSError`` can
catch anything from this taxonomy, while ``severity``/``retryable``/
``service`` attributes let callers make informed decisions instead of
guessing from a bare Exception.
"""
from __future__ import annotations


class MarketOSError(Exception):
    """Base class for all MarketOS-raised (as opposed to library) errors."""

    severity: str = "error"      # "warning" | "error" | "fatal"
    retryable: bool = False
    service: str = "unknown"

    def __init__(self, message: str, *, service: str | None = None):
        super().__init__(message)
        if service is not None:
            self.service = service


class RetryableError(MarketOSError):
    """Transient failure — timeout, rate limit, 5xx. Safe to retry."""
    severity = "warning"
    retryable = True


class ConfigurationError(MarketOSError):
    """Missing or invalid credentials/config. Retrying won't help."""
    severity = "fatal"
    retryable = False


class SupplierQuoteError(RetryableError):
    """A supplier API returned an error, timed out, or sent a malformed
    response while quoting a product. Retryable — the supplier may be
    having a bad moment, not permanently broken."""
    service = "supplier"


class ValidationError(MarketOSError):
    """Input data failed a validation check (bad price, empty name, ...).
    Not retryable — the caller needs to fix the input, not the network."""
    severity = "warning"
    retryable = False


__all__ = [
    "MarketOSError",
    "RetryableError",
    "ConfigurationError",
    "SupplierQuoteError",
    "ValidationError",
]
