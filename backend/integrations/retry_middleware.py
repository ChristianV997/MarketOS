"""backend.integrations.retry_middleware — bounded retry with backoff.

One tiny, dependency-free primitive shared by every integration:

    from backend.integrations.retry_middleware import retry_call

    resp = retry_call(lambda: requests.post(url, ...), attempts=3)

Retries only on transient failures (connection errors, timeouts, HTTP 429
and 5xx when the exception exposes a response) — a 400/401/403 fails fast,
because retrying a bad request just burns quota.  Exponential backoff with
jitter avoids thundering-herd against a recovering API.
"""
from __future__ import annotations

import logging
import random
import time
from typing import Any, Callable, TypeVar

_log = logging.getLogger(__name__)

T = TypeVar("T")

# HTTP status codes worth retrying
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _is_retryable(exc: Exception) -> bool:
    """Transient network failure or retryable HTTP status?"""
    # requests.HTTPError carries .response; anything with a retryable code
    response = getattr(exc, "response", None)
    if response is not None:
        status = getattr(response, "status_code", None)
        return status in _RETRYABLE_STATUS
    # Connection-level problems: requests wraps them all in ConnectionError /
    # Timeout subclasses of IOError; stdlib urllib raises OSError variants.
    return isinstance(exc, (ConnectionError, TimeoutError, OSError))


def retry_call(
    fn: Callable[[], T],
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    retryable: Callable[[Exception], bool] = _is_retryable,
    label: str = "",
) -> T:
    """Call ``fn`` with bounded retries on transient failures.

    Raises the last exception when every attempt fails, or immediately on a
    non-retryable error.  Sleeps base_delay × 2^attempt (±25% jitter),
    capped at max_delay.
    """
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            last_exc = exc
            if not retryable(exc) or attempt == attempts - 1:
                raise
            delay = min(base_delay * (2 ** attempt), max_delay)
            delay *= random.uniform(0.75, 1.25)
            _log.debug("retry attempt=%d/%d label=%s delay=%.2fs error=%s",
                       attempt + 1, attempts, label, delay, exc)
            time.sleep(delay)
    raise last_exc  # type: ignore[misc]  # unreachable, keeps type-checkers happy


__all__ = ["retry_call"]
