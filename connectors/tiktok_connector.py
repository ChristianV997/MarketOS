"""tiktok_connector — stub/live TikTok Research API connector.

Returns raw trend payloads shaped like TikTok Research API responses.
Swap _fetch_live() for a real HTTP call when credentials are available.

Environment:
    TIKTOK_RESEARCH_TOKEN  Bearer token for TikTok Research API (optional).
"""
from __future__ import annotations
import os

_ACCESS_TOKEN = os.getenv("TIKTOK_RESEARCH_TOKEN", "")

_STUB: list[dict] = [
    {
        "video_id": "7001000000000000001",
        "url": "https://www.tiktok.com/@creator1/video/7001000000000000001",
        "description": "Best AI productivity tools to scale your business #productivity",
        "author": "creator1",
        "likes": 128_000,
        "comments": 3_400,
        "shares": 8_900,
        "views": 2_100_000,
        "created_at": "2025-05-01T08:00:00Z",
    },
    {
        "video_id": "7001000000000000002",
        "url": "https://www.tiktok.com/@creator2/video/7001000000000000002",
        "description": "How to make money with automation and ChatGPT #makemoney",
        "author": "creator2",
        "likes": 95_000,
        "comments": 2_100,
        "shares": 6_200,
        "views": 1_800_000,
        "created_at": "2025-05-01T09:00:00Z",
    },
    {
        "video_id": "7001000000000000003",
        "url": "https://www.tiktok.com/@creator3/video/7001000000000000003",
        "description": "Secret productivity hack that earned me $10k this month",
        "author": "creator3",
        "likes": 210_000,
        "comments": 5_800,
        "shares": 14_300,
        "views": 3_400_000,
        "created_at": "2025-05-01T10:00:00Z",
    },
    {
        "video_id": "7001000000000000004",
        "url": "https://www.tiktok.com/@creator4/video/7001000000000000004",
        "description": "The growth tool every founder needs to scale in 2025",
        "author": "creator4",
        "likes": 67_000,
        "comments": 1_900,
        "shares": 4_100,
        "views": 980_000,
        "created_at": "2025-05-01T11:00:00Z",
    },
    {
        "video_id": "7001000000000000005",
        "url": "https://www.tiktok.com/@creator5/video/7001000000000000005",
        "description": "Worth every penny — this automation tool saves 3 hours per day",
        "author": "creator5",
        "likes": 145_000,
        "comments": 4_200,
        "shares": 11_000,
        "views": 2_700_000,
        "created_at": "2025-05-01T12:00:00Z",
    },
]


def _fetch_live(limit: int) -> list[dict]:
    raise NotImplementedError("TikTok Research API integration not yet configured")


def fetch_trending(limit: int = 20) -> list[dict]:
    """Return raw trend items. Falls back to stub when unconfigured."""
    if _ACCESS_TOKEN:
        try:
            return _fetch_live(limit)
        except Exception:
            pass
    return _STUB[:limit]
