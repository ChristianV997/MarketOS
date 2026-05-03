"""schemas — typed signal schemas for the signals subsystem."""
from __future__ import annotations
from typing import TypedDict


class TikTokSignal(TypedDict):
    source: str       # always "tiktok"
    video_id: str
    url: str
    description: str
    author: str
    likes: int
    comments: int
    shares: int
    views: int
    created_at: str   # ISO 8601 from input payload; empty string if absent
