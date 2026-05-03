"""notion_client — minimal Notion API client (stdlib urllib only, no third-party deps)."""
from __future__ import annotations
import json
import urllib.error
import urllib.request

_NOTION_API_BASE = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"
_TIMEOUT = 3


def create_page(token: str, database_id: str, name: str, data: str) -> str | None:
    """Create a page in a Notion database with Name (title) + Data (rich_text) properties.

    Returns the Notion page id on success, raises RuntimeError on HTTP/network failure.
    """
    payload = {
        "parent": {"database_id": database_id},
        "properties": {
            "Name": {"title": [{"text": {"content": name[:2000]}}]},
            "Data": {"rich_text": [{"text": {"content": data[:2000]}}]},
        },
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    req = urllib.request.Request(
        f"{_NOTION_API_BASE}/pages",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": _NOTION_VERSION,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            result = json.loads(resp.read())
            return result.get("id")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from exc
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc
