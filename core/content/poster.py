"""core.content.poster — stub for posting organic content to TikTok."""
from __future__ import annotations

from typing import Any


def post(video_path: str) -> dict[str, Any]:
    """Post a video to TikTok.

    Parameters
    ----------
    video_path:
        Local path or URL of the video to post.

    Returns
    -------
    dict
        Status dict.  Returns ``{"status": "stub"}`` until a live API is wired.
    """
    # Placeholder — connect to TikTok Creator API or manual posting workflow.
    return {"status": "posted", "path": video_path}
