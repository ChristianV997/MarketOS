"""Tests for backend.observability.exporters."""
from backend.observability.exporters import (
    prometheus_text, cognition_json, entropy_json,
    recent_traces_json, topology_json,
)


def test_prometheus_text_is_string():
    result = prometheus_text()
    assert isinstance(result, str)


def test_prometheus_text_not_empty():
    result = prometheus_text()
    assert len(result) > 0


def test_cognition_json_returns_dict():
    result = cognition_json(workspace="test")
    assert isinstance(result, dict)


def test_cognition_json_has_workspace():
    result = cognition_json(workspace="myws")
    assert result.get("workspace") == "myws"


def test_entropy_json_returns_dict():
    result = entropy_json(workspace="test")
    assert isinstance(result, dict)


def test_entropy_json_overall_entropy():
    result = entropy_json(workspace="test")
    assert "overall_entropy" in result


def test_recent_traces_json_returns_list():
    result = recent_traces_json(n=5)
    assert isinstance(result, list)


def test_topology_json_returns_dict():
    result = topology_json(workspace="test")
    assert isinstance(result, dict)
