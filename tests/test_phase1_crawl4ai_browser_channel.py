from backend.adapters.research.crawl4ai import (
    CRAWL4AI_BROWSER_CHANNEL_ENV,
    crawl4ai_browser_channel,
)


def test_crawl4ai_browser_channel_is_off_by_default(monkeypatch):
    monkeypatch.delenv(CRAWL4AI_BROWSER_CHANNEL_ENV, raising=False)

    assert crawl4ai_browser_channel() is None


def test_crawl4ai_browser_channel_requires_explicit_operator_override(monkeypatch):
    monkeypatch.setenv(CRAWL4AI_BROWSER_CHANNEL_ENV, " chrome ")

    assert crawl4ai_browser_channel() == "chrome"
