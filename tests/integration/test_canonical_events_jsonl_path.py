"""Regression tests for GET /api/events JSONL path fail-closed behavior."""
from __future__ import annotations

from fastapi import HTTPException

from api.routes import canonical_events
from backend.events import query_service
from backend.events.query_models import EventQuery


def _query() -> EventQuery:
    return EventQuery(None, None, None, None, None, None, 100, 0)


def test_jsonl_path_resolution_error_returns_empty_read_only_report(monkeypatch):
    class RaisingPath:
        def __init__(self, _: str):
            pass

        def resolve(self):
            raise RuntimeError("synthetic symlink loop")

    monkeypatch.setenv("MARKETOS_EVENT_READ_JSONL_PATH", "synthetic")
    monkeypatch.setattr(canonical_events, "Path", RaisingPath)

    report = canonical_events._jsonl_report(_query())

    assert report["read_only"] is True
    assert report["network_calls"] is False
    assert report["mutated"] is False
    assert report["timeline"]["events"] == []
    assert report["timeline"]["warnings"] == ["jsonl_read_path_unconfigured"]
    assert report["opportunity_rankings"] == []
    assert report["competition_summaries"] == []
    assert report["research_portfolios"] == []


def test_jsonl_directory_under_artifacts_is_unconfigured(monkeypatch, tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setattr(canonical_events, "ARTIFACTS", artifacts.resolve())
    monkeypatch.setenv("MARKETOS_EVENT_READ_JSONL_PATH", str(artifacts))

    report = canonical_events._jsonl_report(_query())

    assert report["timeline"]["warnings"] == ["jsonl_read_path_unconfigured"]
    assert report["timeline"]["events"] == []
    assert report["read_only"] is True


def test_jsonl_oversized_artifact_is_rejected_before_read(monkeypatch, tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    path = artifacts / "events.jsonl"
    path.write_bytes(b"x" * (canonical_events.MAX_JSONL_BYTES + 1))
    monkeypatch.setattr(canonical_events, "ARTIFACTS", artifacts.resolve())
    monkeypatch.setenv("MARKETOS_EVENT_READ_JSONL_PATH", str(path))

    calls = []
    original_loader = canonical_events.load_events_from_jsonl

    def _bounded_loader(path, *, max_bytes, oversized_warning):
        calls.append(max_bytes)
        return original_loader(path, max_bytes=max_bytes, oversized_warning=oversized_warning)

    monkeypatch.setattr(canonical_events, "load_events_from_jsonl", _bounded_loader)
    report = canonical_events._jsonl_report(_query())

    assert calls == [canonical_events.MAX_JSONL_BYTES]
    assert report["timeline"]["warnings"] == ["jsonl_read_path_oversized"]
    assert report["timeline"]["events"] == []
    assert report["read_only"] is True
    assert report["mutated"] is False


def test_jsonl_oversized_actual_read_never_reaches_event_parser(monkeypatch, tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    path = artifacts / "events.jsonl"
    path.write_bytes((b"{}\n" * ((canonical_events.MAX_JSONL_BYTES // 3) + 1)))
    monkeypatch.setattr(canonical_events, "ARTIFACTS", artifacts.resolve())
    monkeypatch.setenv("MARKETOS_EVENT_READ_JSONL_PATH", str(path))

    def _must_not_parse(_mapping):
        raise AssertionError("oversized JSONL must not reach Event.from_dict")

    monkeypatch.setattr(query_service.Event, "from_dict", _must_not_parse)
    report = canonical_events._jsonl_report(_query())

    assert report["timeline"]["warnings"] == ["jsonl_read_path_oversized"]
    assert report["timeline"]["events"] == []


def test_jsonl_path_outside_artifacts_still_forbidden(monkeypatch, tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    outsider = tmp_path / "outside.jsonl"
    outsider.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(canonical_events, "ARTIFACTS", artifacts.resolve())
    monkeypatch.setenv("MARKETOS_EVENT_READ_JSONL_PATH", str(outsider))

    try:
        canonical_events._jsonl_report(_query())
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("expected HTTP 403 for a path outside artifacts/")
