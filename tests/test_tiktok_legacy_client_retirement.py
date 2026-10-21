"""Legacy TikTok clients stay offline and unregistered.

The registered discovery adapter remains backend.adapters.tiktok_organic.
These tests do not import that adapter and do not perform network I/O.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY = (
    ROOT / "core" / "sensors" / "tiktok_client.py",
    ROOT / "connectors" / "tiktok_connector.py",
)
PRODUCTION_ROOTS = ("api", "backend", "core", "marketos", "orchestrator", "services")
FORBIDDEN_SNIPPETS = (
    "RAPIDAPI_KEY",
    "TIKTOK_RESEARCH_TOKEN",
    "os.environ",
    "os.getenv",
    "getenv",
    "requests",
    "urllib",
    "http.client",
    "rapidapi",
    "business-api.tiktok.com",
    "open.tiktokapis.com",
    "register_source",
    "discovery_registry",
    "_fetch_live",
    "_ACCESS_TOKEN",
    "X-RapidAPI",
)


def _python_files(*roots: str) -> list[Path]:
    found: list[Path] = []
    for root_name in roots:
        root = ROOT / root_name
        if root.is_dir():
            found.extend(path for path in root.rglob("*.py") if path.is_file())
    return found


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_legacy_sources_have_no_live_or_credential_surface():
    for path in LEGACY:
        lowered = path.read_text(encoding="utf-8").lower()
        for snippet in FORBIDDEN_SNIPPETS:
            assert snippet.lower() not in lowered, f"{path.name} still contains {snippet}"


def test_fetch_ignores_retired_credential_names(monkeypatch):
    monkeypatch.setenv("RAPIDAPI_KEY", "present-but-unread")
    monkeypatch.setenv("TIKTOK_RESEARCH_TOKEN", "present-but-unread")
    client = importlib.reload(importlib.import_module("core.sensors.tiktok_client"))
    connector = importlib.reload(importlib.import_module("connectors.tiktok_connector"))

    assert client.fetch_trending() == []
    assert client.fetch_trending(count=5) == []
    assert client.fetch_trending(count="5") == []

    rows = connector.fetch_trending(limit=2)
    assert [row["video_id"] for row in rows] == [
        "7001000000000000001",
        "7001000000000000002",
    ]
    assert len(connector.fetch_trending(limit=20)) == 5
    assert connector.fetch_trending(limit=0) == []


def test_daily_research_keeps_empty_list_contract():
    from core.jobs import daily_research

    importlib.reload(daily_research)
    assert daily_research.run() == []


def test_production_import_graph_has_one_legacy_caller():
    client_importers: list[str] = []
    connector_importers: list[str] = []
    for path in _python_files(*PRODUCTION_ROOTS):
        modules = _imported_modules(path)
        rel = path.relative_to(ROOT).as_posix()
        if "core.sensors.tiktok_client" in modules:
            client_importers.append(rel)
        if "connectors.tiktok_connector" in modules:
            connector_importers.append(rel)
    assert client_importers == ["core/jobs/daily_research.py"]
    assert connector_importers == []


def test_only_tiktok_organic_is_registered():
    signals = (ROOT / "core" / "signals.py").read_text(encoding="utf-8")
    assert "backend.adapters.tiktok_organic" in signals
    assert "tiktok_client" not in signals
    assert "tiktok_connector" not in signals

    registered: list[tuple[str, str]] = []
    for path in _python_files("backend", "core"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {"register_source", "register"} or not node.args:
                continue
            first = node.args[0]
            if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
                continue
            if "tiktok" not in first.value.lower():
                continue
            registered.append((path.relative_to(ROOT).as_posix(), first.value))

    assert sorted(registered) == [
        ("backend/adapters/tiktok_organic.py", "tiktok_organic"),
        ("backend/adapters/tiktok_organic.py", "tiktok_organic"),
    ]
