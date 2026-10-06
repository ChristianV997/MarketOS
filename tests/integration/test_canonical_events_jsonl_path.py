"""Regression tests for GET /api/events JSONL path fail-closed behavior."""
from __future__ import annotations

import os
import threading

import pytest
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


def _valid_event_line() -> bytes:
    from pathlib import Path

    fixture = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "event_queries" / "mixed_canonical_events.jsonl"
    return fixture.read_bytes().splitlines()[0] + b"\n"


def test_exact_one_mib_jsonl_is_read_and_one_extra_byte_is_not(monkeypatch, tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    line = _valid_event_line()
    exact = artifacts / "exact.jsonl"
    body = line * (canonical_events.MAX_JSONL_BYTES // len(line))
    remainder = canonical_events.MAX_JSONL_BYTES - len(body)
    if remainder:
        body += b" " * (remainder - 1) + b"\n"
    assert len(body) == canonical_events.MAX_JSONL_BYTES
    exact.write_bytes(body)
    over = artifacts / "over.jsonl"
    over.write_bytes(body + b"\n")
    monkeypatch.setattr(canonical_events, "ARTIFACTS", artifacts.resolve())

    monkeypatch.setenv("MARKETOS_EVENT_READ_JSONL_PATH", str(exact))
    accepted = canonical_events._jsonl_report(_query())
    assert accepted["timeline"]["events"]
    assert "jsonl_read_path_oversized" not in accepted["timeline"]["warnings"]
    assert accepted["read_only"] is True
    assert accepted["network_calls"] is False
    assert accepted["mutated"] is False

    monkeypatch.setenv("MARKETOS_EVENT_READ_JSONL_PATH", str(over))
    rejected = canonical_events._jsonl_report(_query())
    assert rejected["timeline"]["events"] == []
    assert rejected["timeline"]["warnings"] == ["jsonl_read_path_oversized"]


def test_undecodable_jsonl_fail_closes_without_parsing(monkeypatch, tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setattr(canonical_events, "ARTIFACTS", artifacts.resolve())

    def _must_not_parse(_mapping):
        raise AssertionError("undecodable JSONL must not reach Event.from_dict")

    monkeypatch.setattr(query_service.Event, "from_dict", _must_not_parse)
    for name, payload in (
        ("small.jsonl", b"\xff\xfe"),
        ("exact.jsonl", b" " * (canonical_events.MAX_JSONL_BYTES - 1) + b"\xff"),
    ):
        path = artifacts / name
        path.write_bytes(payload)
        assert len(payload) <= canonical_events.MAX_JSONL_BYTES
        monkeypatch.setenv("MARKETOS_EVENT_READ_JSONL_PATH", str(path))
        report = canonical_events._jsonl_report(_query())
        assert report["timeline"]["events"] == []
        assert report["timeline"]["warnings"] == ["jsonl_file_unavailable"]
        assert report["read_only"] is True
        assert report["mutated"] is False
        assert report["network_calls"] is False


def test_existing_get_returns_in_jail_jsonl_events(monkeypatch, tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    path = artifacts / "events.jsonl"
    path.write_bytes(_valid_event_line())
    monkeypatch.setattr(canonical_events, "ARTIFACTS", artifacts.resolve())
    monkeypatch.setenv("MARKETOS_EVENT_READ_JSONL_PATH", str(path))

    report = canonical_events.events(limit=100, offset=0, source="jsonl", request=None)

    assert report["read_only"] is True
    assert report["network_calls"] is False
    assert report["mutated"] is False
    assert report["timeline"]["events"][0]["event_id"] == "commerce-start"
    assert report["timeline"]["warnings"] == []


def test_jsonl_nonexistent_file_returns_unconfigured_report(monkeypatch, tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    nonexistent = artifacts / "missing.jsonl"
    monkeypatch.setattr(canonical_events, "ARTIFACTS", artifacts.resolve())
    monkeypatch.setenv("MARKETOS_EVENT_READ_JSONL_PATH", str(nonexistent))

    report = canonical_events._jsonl_report(_query())

    assert report["read_only"] is True
    assert report["network_calls"] is False
    assert report["mutated"] is False
    assert report["timeline"]["events"] == []
    assert report["timeline"]["warnings"] == ["jsonl_read_path_unconfigured"]


def test_jsonl_malformed_and_non_finite_rows_do_not_leak_contents(monkeypatch, tmp_path):
    import json

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    path = artifacts / "mixed.jsonl"
    secret_marker = "SUPER_SECRET_VALUE_DO_NOT_LEAK_12345"
    lines = [
        b"{invalid_syntax\n",
        f'{{"event_id": "{secret_marker}", "broken": true}}\n'.encode("utf-8"),
        b'{"event_id": "e_nan", "workspace_id": "w", "aggregate_type": "a", "aggregate_id": "i", "event_type": "t", "schema_version": 1, "occurred_at": NaN, "source": "s", "payload": {}, "metadata": {}}\n',
        _valid_event_line(),
    ]
    path.write_bytes(b"".join(lines))
    monkeypatch.setattr(canonical_events, "ARTIFACTS", artifacts.resolve())
    monkeypatch.setenv("MARKETOS_EVENT_READ_JSONL_PATH", str(path))

    report = canonical_events._jsonl_report(_query())

    assert report["read_only"] is True
    assert report["network_calls"] is False
    assert report["mutated"] is False
    assert len(report["timeline"]["events"]) == 1
    assert report["timeline"]["events"][0]["event_id"] == "commerce-start"
    assert "malformed_jsonl_row:1" in report["timeline"]["warnings"]
    assert "malformed_jsonl_row:2" in report["timeline"]["warnings"]
    assert "malformed_jsonl_row:3" in report["timeline"]["warnings"]
    # Ensure raw secret content is not in warnings or any report field
    serialized = json.dumps(report)
    assert secret_marker not in serialized


def test_jsonl_byte_cap_applies_to_stream_consumed_bytes(monkeypatch, tmp_path):
    class StreamTracker:
        def __init__(self, raw):
            self._raw = raw
            self.read_calls: list[int] = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self._raw.close()

        def read(self, size: int = -1) -> bytes:
            self.read_calls.append(size)
            return self._raw.read(size)

    file_path = tmp_path / "stream.jsonl"
    file_path.write_bytes(b"a" * 100)
    trackers: list[StreamTracker] = []
    orig_open = open

    def mock_open(file, mode="r", *args, **kwargs):
        opened = orig_open(file, mode, *args, **kwargs)
        if isinstance(file, int) and "b" in mode:
            wrapped = StreamTracker(opened)
            trackers.append(wrapped)
            return wrapped
        return opened

    monkeypatch.setattr("builtins.open", mock_open)
    events, warnings = query_service.load_events_from_jsonl(file_path, max_bytes=50, oversized_warning="oversized")

    assert events == []
    assert warnings == ["oversized"]
    assert trackers and trackers[0].read_calls == [50, 1]


def _jail(monkeypatch, tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setattr(canonical_events, "ARTIFACTS", artifacts.resolve())
    return artifacts


@pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\u0085"], ids=["U+2028", "U+2029", "U+0085"])
def test_valid_row_with_raw_unicode_line_separator_round_trips(monkeypatch, tmp_path, separator):
    """json.dumps(ensure_ascii=False) keeps these raw; str.splitlines() would cut the row in two."""
    from backend.contracts.events import Event

    event = Event("sep-1", "w", "agg", "a1", "t", 1, 1.0, source="s", payload={"note": f"line one{separator}line two"})
    neighbour = Event("sep-2", "w", "agg", "a1", "t", 1, 2.0, source="s")
    artifacts = _jail(monkeypatch, tmp_path)
    path = artifacts / "events.jsonl"
    path.write_bytes((event.canonical_json() + "\n" + neighbour.canonical_json() + "\n").encode("utf-8"))
    monkeypatch.setenv("MARKETOS_EVENT_READ_JSONL_PATH", str(path))

    loaded, warnings = query_service.load_events_from_jsonl(path)
    assert warnings == []
    assert [item.replay_hash() for item in loaded] == [event.replay_hash(), neighbour.replay_hash()]

    report = canonical_events._jsonl_report(_query())
    assert report["timeline"]["warnings"] == []
    assert sorted(item["event_id"] for item in report["timeline"]["events"]) == ["sep-1", "sep-2"]


@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"], ids=["LF", "CRLF", "CR"])
def test_supported_line_endings_still_split_rows(tmp_path, ending):
    line = _valid_event_line().rstrip(b"\n").decode("utf-8")
    path = tmp_path / "events.jsonl"
    path.write_bytes((line + ending + line + ending).encode("utf-8"))
    loaded, warnings = query_service.load_events_from_jsonl(path)
    assert warnings == [] and len(loaded) == 2


def test_blank_line_between_rows_is_still_one_malformed_row(tmp_path):
    line = _valid_event_line().rstrip(b"\n")
    path = tmp_path / "events.jsonl"
    path.write_bytes(line + b"\n\n" + line + b"\n")
    loaded, warnings = query_service.load_events_from_jsonl(path)
    assert len(loaded) == 2 and warnings == ["malformed_jsonl_row:2"]


@pytest.mark.parametrize("cap", [-1, -5, 1.5, "5", True, False], ids=repr)
def test_invalid_byte_cap_is_rejected_and_never_disables_the_bound(tmp_path, cap):
    path = tmp_path / "events.jsonl"
    path.write_bytes(_valid_event_line() * 50)
    with pytest.raises(ValueError, match="max_bytes"):
        query_service.load_events_from_jsonl(path, max_bytes=cap)


def test_zero_byte_cap_rejects_any_non_empty_file_as_oversized(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_bytes(_valid_event_line())
    assert query_service.load_events_from_jsonl(path, max_bytes=0, oversized_warning="big") == ([], ["big"])


def test_loader_fails_closed_on_nul_path_and_overflowing_cap(tmp_path):
    assert query_service.load_events_from_jsonl("events\x00.jsonl") == ([], ["jsonl_file_unavailable"])
    path = tmp_path / "events.jsonl"
    path.write_bytes(_valid_event_line())
    assert query_service.load_events_from_jsonl(path, max_bytes=10**30) == ([], ["jsonl_file_unavailable"])


def test_overlong_path_component_returns_empty_report_instead_of_raising(monkeypatch, tmp_path):
    artifacts = _jail(monkeypatch, tmp_path)
    monkeypatch.setenv("MARKETOS_EVENT_READ_JSONL_PATH", str(artifacts / ("a" * 300 + ".jsonl")))

    report = canonical_events._jsonl_report(_query())

    assert report["timeline"]["warnings"] == ["jsonl_read_path_unconfigured"]
    assert report["timeline"]["events"] == []
    assert report["read_only"] is True and report["mutated"] is False and report["network_calls"] is False


def test_real_symlink_loop_inside_artifacts_returns_empty_report(monkeypatch, tmp_path):
    artifacts = _jail(monkeypatch, tmp_path)
    first, second = artifacts / "loop-a.jsonl", artifacts / "loop-b.jsonl"
    try:
        first.symlink_to(second)
        second.symlink_to(first)
    except OSError:
        pytest.skip("symlinks are not available on this platform")
    monkeypatch.setenv("MARKETOS_EVENT_READ_JSONL_PATH", str(first))

    report = canonical_events._jsonl_report(_query())

    assert report["timeline"]["warnings"] == ["jsonl_read_path_unconfigured"]
    assert report["timeline"]["events"] == []


def test_symlink_inside_artifacts_pointing_outside_is_forbidden(monkeypatch, tmp_path):
    artifacts = _jail(monkeypatch, tmp_path)
    outsider = tmp_path / "outside.jsonl"
    outsider.write_bytes(_valid_event_line())
    link = artifacts / "link.jsonl"
    try:
        link.symlink_to(outsider)
    except OSError:
        pytest.skip("symlinks are not available on this platform")
    monkeypatch.setenv("MARKETOS_EVENT_READ_JSONL_PATH", str(link))

    with pytest.raises(HTTPException) as excinfo:
        canonical_events._jsonl_report(_query())
    assert excinfo.value.status_code == 403


def test_operator_jsonl_cap_is_exactly_one_mib():
    assert canonical_events.MAX_JSONL_BYTES == 1_048_576


def test_sibling_directory_sharing_the_artifacts_prefix_is_forbidden(monkeypatch, tmp_path):
    artifacts = _jail(monkeypatch, tmp_path)
    sibling = tmp_path / (artifacts.name + "_evil")
    sibling.mkdir()
    target = sibling / "events.jsonl"
    target.write_bytes(_valid_event_line())
    monkeypatch.setenv("MARKETOS_EVENT_READ_JSONL_PATH", str(target))

    with pytest.raises(HTTPException) as excinfo:
        canonical_events._jsonl_report(_query())
    assert excinfo.value.status_code == 403


@pytest.mark.parametrize("error", [OSError("synthetic"), ValueError("synthetic")], ids=["OSError", "ValueError"])
def test_resolution_oserror_and_valueerror_return_empty_report(monkeypatch, error):
    class RaisingPath:
        def __init__(self, _: str):
            pass

        def resolve(self):
            raise error

    monkeypatch.setenv("MARKETOS_EVENT_READ_JSONL_PATH", "synthetic")
    monkeypatch.setattr(canonical_events, "Path", RaisingPath)

    report = canonical_events._jsonl_report(_query())

    assert report["timeline"]["warnings"] == ["jsonl_read_path_unconfigured"]
    assert report["read_only"] is True and report["mutated"] is False


def test_loader_returns_unavailable_when_the_path_cannot_be_opened(tmp_path):
    assert query_service.load_events_from_jsonl(tmp_path) == ([], ["jsonl_file_unavailable"])
    assert query_service.load_events_from_jsonl(tmp_path / "missing.jsonl") == ([], ["jsonl_file_unavailable"])


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are not available on this platform")
def test_fifo_direct_loader_fails_promptly_in_subprocess(tmp_path):
    import subprocess
    import sys

    fifo = tmp_path / "events.fifo"
    getattr(os, "mkfifo")(fifo)
    script = (
        "import sys\n"
        "from backend.events.query_service import load_events_from_jsonl\n"
        "events, warnings = load_events_from_jsonl(sys.argv[1])\n"
        "assert events == [], f'expected empty events, got {events}'\n"
        "assert warnings == ['jsonl_file_unavailable'], f'expected unavailable warning, got {warnings}'\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script, str(fifo)],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert proc.returncode == 0, f"stdout: {proc.stdout}, stderr: {proc.stderr}"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are not available on this platform")
def test_fifo_direct_loader_fails_promptly_in_process(tmp_path):
    fifo = tmp_path / "events.fifo"
    getattr(os, "mkfifo")(fifo)
    loaded, warnings = query_service.load_events_from_jsonl(fifo)
    assert loaded == []
    assert warnings == ["jsonl_file_unavailable"]


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are not available on this platform")
def test_fifo_under_artifacts_is_not_a_file_and_does_not_block(monkeypatch, tmp_path):
    artifacts = _jail(monkeypatch, tmp_path)
    fifo = artifacts / "events.jsonl"
    getattr(os, "mkfifo")(fifo)
    monkeypatch.setenv("MARKETOS_EVENT_READ_JSONL_PATH", str(fifo))
    outcome: list[dict] = []
    worker = threading.Thread(target=lambda: outcome.append(canonical_events._jsonl_report(_query())), daemon=True)
    worker.start()
    worker.join(timeout=5)
    if worker.is_alive():  # a regression would block in open(); release it before failing
        release = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
        os.close(release)
        worker.join(timeout=5)
        pytest.fail("a FIFO must be rejected as a non-file instead of blocking the read")

    assert outcome[0]["timeline"]["warnings"] == ["jsonl_read_path_unconfigured"]
    assert outcome[0]["timeline"]["events"] == []


def test_regular_file_direct_loader_and_route(monkeypatch, tmp_path):
    artifacts = _jail(monkeypatch, tmp_path)
    path = artifacts / "events.jsonl"
    line = _valid_event_line()
    path.write_bytes(line)
    monkeypatch.setenv("MARKETOS_EVENT_READ_JSONL_PATH", str(path))

    # Direct loader caller
    events, warnings = query_service.load_events_from_jsonl(path)
    assert warnings == []
    assert len(events) == 1

    # Route caller
    report = canonical_events._jsonl_report(_query())
    assert report["timeline"]["warnings"] == []
    assert len(report["timeline"]["events"]) == 1
    assert report["read_only"] is True
    assert report["network_calls"] is False
    assert report["mutated"] is False
