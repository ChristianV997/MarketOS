"""Tests for backend.ollama_manager.OllamaManager — health, models, sizing."""
from unittest.mock import MagicMock, patch

import pytest

from backend.ollama_manager import (
    OllamaManager,
    RECOMMENDED_MODELS,
    _DEFAULT_RESOURCE_ESTIMATE,
)


def _mock_response(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status.side_effect = (
        None if status_code == 200 else Exception(f"HTTP {status_code}")
    )
    return resp


# ── is_healthy ────────────────────────────────────────────────────────────────

def test_explicit_probe_health_reports_ready_when_daemon_responds():
    manager = OllamaManager()
    manager._enabled = True
    with patch("httpx.get", return_value=_mock_response(200)):
        assert manager.probe_health() == "ready"


def test_explicit_probe_health_reports_unavailable_when_daemon_unreachable():
    manager = OllamaManager()
    manager._enabled = True
    with patch("httpx.get", side_effect=ConnectionError("refused")):
        assert manager.probe_health() == "unavailable"


def test_explicit_probe_health_fails_soft_when_daemon_unreachable():
    manager = OllamaManager()
    manager._enabled = True
    with patch("httpx.get", side_effect=ConnectionError("refused")):
        assert manager.probe_health() == "unavailable"


def test_disabled_manager_does_not_probe_or_pull():
    manager = OllamaManager()
    with patch("httpx.get") as get_mock, patch("httpx.stream") as stream_mock:
        assert manager.probe_health() == "blocked"
        assert manager.list_models() == []
        assert manager.pull_model("mistral:7b") is False
    get_mock.assert_not_called()
    stream_mock.assert_not_called()


# ── list_models ───────────────────────────────────────────────────────────────

def test_list_models_parses_tags_payload():
    manager = OllamaManager()
    manager._enabled = True
    payload = {"models": [{"name": "mistral:7b"}, {"name": "llama3.2:3b"}]}
    with patch("httpx.get", return_value=_mock_response(200, payload)):
        assert manager.list_models() == ["mistral:7b", "llama3.2:3b"]


def test_list_models_empty_when_unreachable():
    manager = OllamaManager()
    manager._enabled = True
    with patch("httpx.get", side_effect=ConnectionError("refused")):
        assert manager.list_models() == []


# ── pull_model ────────────────────────────────────────────────────────────────

def test_pull_model_noops_when_already_present():
    manager = OllamaManager()
    manager._enabled = True
    with patch.object(manager, "list_models", return_value=["mistral:7b"]):
        with patch("httpx.stream") as stream_mock:
            assert manager.pull_model("mistral:7b") is True
            stream_mock.assert_not_called()


def test_pull_model_calls_api_pull_when_absent():
    manager = OllamaManager()
    manager._enabled = True
    stream_ctx = MagicMock()
    stream_ctx.__enter__.return_value.iter_lines.return_value = iter([b'{"status":"success"}'])
    stream_ctx.__enter__.return_value.raise_for_status.return_value = None
    with patch.object(manager, "list_models", return_value=[]):
        with patch("httpx.stream", return_value=stream_ctx) as stream_mock:
            assert manager.pull_model("mistral:7b") is True
            stream_mock.assert_called_once()
            _, kwargs = stream_mock.call_args
            assert kwargs["json"] == {"name": "mistral:7b"}


def test_pull_model_returns_false_on_failure():
    manager = OllamaManager()
    with patch.object(manager, "list_models", return_value=[]):
        with patch("httpx.stream", side_effect=ConnectionError("refused")):
            assert manager.pull_model("mistral:7b") is False


# ── ensure_model ──────────────────────────────────────────────────────────────

def test_ensure_model_delegates_to_pull_model():
    manager = OllamaManager()
    with patch.object(manager, "pull_model", return_value=True) as pull_mock:
        assert manager.ensure_model("mistral:7b") is True
        pull_mock.assert_called_once_with("mistral:7b")


def test_ensure_model_never_raises():
    manager = OllamaManager()
    with patch.object(manager, "pull_model", side_effect=RuntimeError("boom")):
        assert manager.ensure_model("mistral:7b") is False


# ── estimate_resource_needs ───────────────────────────────────────────────────

@pytest.mark.parametrize("model", list(RECOMMENDED_MODELS.keys()))
def test_estimate_resource_needs_known_models(model):
    manager = OllamaManager()
    estimate = manager.estimate_resource_needs(model)
    assert estimate == RECOMMENDED_MODELS[model]


def test_estimate_resource_needs_unknown_model_returns_default():
    manager = OllamaManager()
    estimate = manager.estimate_resource_needs("some-unknown-model:latest")
    assert estimate == _DEFAULT_RESOURCE_ESTIMATE


# ── router integration ────────────────────────────────────────────────────────

def test_router_construction_does_not_probe_ollama():
    from backend.inference.router import InferenceRouter
    from backend.inference.providers.ollama import OllamaProvider
    from backend.inference.providers.mock import MockProvider

    with patch("httpx.get") as get_mock, patch("subprocess.Popen") as popen_mock:
        router = InferenceRouter(providers=[OllamaProvider(), MockProvider()])
    assert router is not None
    get_mock.assert_not_called()
    popen_mock.assert_not_called()


def test_router_ensure_model_skipped_when_no_ollama_provider():
    from backend.inference.router import InferenceRouter
    from backend.inference.providers.mock import MockProvider

    with patch("backend.ollama_manager.OllamaManager.ensure_model") as ensure_mock:
        InferenceRouter(providers=[MockProvider()])
        ensure_mock.assert_not_called()


def test_router_does_not_ensure_ollama_model_on_construction():
    from backend.inference.router import InferenceRouter
    from backend.inference.providers.ollama import OllamaProvider
    from backend.inference.providers.mock import MockProvider

    with patch("backend.ollama_manager.OllamaManager.ensure_model") as ensure_mock:
        InferenceRouter(providers=[OllamaProvider(), MockProvider()])
    ensure_mock.assert_not_called()
