"""Tests for backend.aws.heartbeat — fail-soft S3 heartbeat push/check."""
import sys
import types
from datetime import datetime, timezone

import backend.aws.heartbeat as hb


def test_push_returns_false_when_no_bucket_configured(monkeypatch):
    monkeypatch.setattr(hb, "_BUCKET", "")
    assert hb.push_heartbeat(node="pc") is False


def test_age_returns_none_when_no_bucket_configured(monkeypatch):
    monkeypatch.setattr(hb, "_BUCKET", "")
    assert hb.heartbeat_age_s() is None


def test_push_returns_false_when_boto3_missing(monkeypatch):
    monkeypatch.setattr(hb, "_BUCKET", "some-bucket")
    monkeypatch.setitem(sys.modules, "boto3", None)  # import boto3 -> ImportError
    assert hb.push_heartbeat(node="pc") is False


def test_age_returns_none_on_s3_error(monkeypatch):
    monkeypatch.setattr(hb, "_BUCKET", "some-bucket")

    class _FailingClient:
        def head_object(self, **kwargs):
            raise RuntimeError("boom")

    fake_boto3 = types.SimpleNamespace(client=lambda *a, **k: _FailingClient())
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    assert hb.heartbeat_age_s() is None


def test_push_calls_put_object_with_bucket_and_key(monkeypatch):
    monkeypatch.setattr(hb, "_BUCKET", "my-bucket")
    monkeypatch.setattr(hb, "_KEY", "orchestrator/heartbeat.json")
    calls = {}

    class _Client:
        def put_object(self, **kwargs):
            calls.update(kwargs)

    fake_boto3 = types.SimpleNamespace(client=lambda *a, **k: _Client())
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)

    assert hb.push_heartbeat(node="pc") is True
    assert calls["Bucket"] == "my-bucket"
    assert calls["Key"] == "orchestrator/heartbeat.json"
    assert b"pc" in calls["Body"]


def test_age_computes_seconds_since_last_modified(monkeypatch):
    monkeypatch.setattr(hb, "_BUCKET", "my-bucket")

    class _Client:
        def head_object(self, **kwargs):
            return {"LastModified": datetime.now(tz=timezone.utc)}

    fake_boto3 = types.SimpleNamespace(client=lambda *a, **k: _Client())
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)

    age = hb.heartbeat_age_s()
    assert age is not None
    assert 0 <= age < 5
