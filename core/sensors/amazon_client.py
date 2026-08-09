"""core.sensors.amazon_client — scrape Amazon bestseller titles."""
from __future__ import annotations

from typing import Any

_BESTSELLERS_URL = "https://www.amazon.com/Best-Sellers/zgbs"


def fetch_bestsellers(url: str = _BESTSELLERS_URL) -> list[dict[str, Any]]:
    """Scrape the top product titles from Amazon Best Sellers.

    Requires ``requests`` and ``beautifulsoup4`` to be installed.  Returns an
    empty list when the dependencies are missing or the request fails.

    Parameters
    ----------
    url:
        Amazon Best Sellers page URL.

    Returns
    -------
    list[dict]
        Each dict contains a ``"title"`` key.
    """
    try:
        import requests  # type: ignore[import]
        from bs4 import BeautifulSoup  # type: ignore[import]
    except ImportError:
        return []

    try:
        html = requests.get(url, timeout=10).text
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return []

    products = []
    for item in soup.select(".zg-grid-general-faceout")[:20]:
        title_el = item.select_one("._cDEzb_p13n-sc-css-line-clamp-3_g3dy1")
        products.append({"title": title_el.text.strip() if title_el else ""})
    return products
