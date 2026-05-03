"""base — BaseSignal TypedDict shared across all scrapers."""
from typing import TypedDict

_VALID_SOURCES = {"tiktok", "youtube", "meta", "google", "amazon", "google_trends", "linkedin"}


class BaseSignal(TypedDict):
    source: str
    raw_text: str
    engagement: float       # [0.0, 1.0]
    category: str
    timestamp: str          # ISO 8601
    url: str
    external_id: str


def validate_signal(s: BaseSignal) -> bool:
    """Return True only if all 8 quality checks pass."""
    if not isinstance(s.get("engagement"), (int, float)):
        return False
    eng = float(s["engagement"])
    if not (0.0 <= eng <= 1.0):
        return False
    if s.get("source") not in _VALID_SOURCES:
        return False
    if not isinstance(s.get("raw_text"), str) or not s["raw_text"].strip():
        return False
    if not isinstance(s.get("category"), str) or not s["category"].strip():
        return False
    url = s.get("url", "")
    if not isinstance(url, str) or not (url.startswith("http://") or url.startswith("https://")):
        return False
    if not isinstance(s.get("timestamp"), str) or not s["timestamp"].strip():
        return False
    if not isinstance(s.get("external_id"), str) or not s["external_id"].strip():
        return False
    if eng < 0.50:
        return False
    return True
