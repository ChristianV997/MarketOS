"""Tests for local inference safety boundaries."""
import sys
from unittest.mock import patch, MagicMock

import pytest

from backend.inference.router import InferenceRouter
from backend.ollama_manager import OllamaManager
from backend.inference.providers.ollama import OllamaProvider
from backend.inference.providers.litellm import LiteLLMProvider
from backend.inference.models.inference_request import InferenceRequest
from backend.inference.models.embedding_request import EmbeddingRequest

def test_router_construction_offline():
    # Router construction must not perform network calls or start processes.
    with patch("subprocess.Popen") as mock_popen, \
         patch("httpx.get") as mock_get:

        InferenceRouter()

        mock_popen.assert_not_called()
        mock_get.assert_not_called()

def test_ollama_default_readiness_is_offline():
    # By default (no env vars), Ollama is not enabled and is_available is False
    provider = OllamaProvider()
    assert not provider.is_available()

    # ensure probe_health doesn't call network when disabled
    with patch("httpx.get") as mock_get:
        assert not provider.probe()
        mock_get.assert_not_called()

def test_litellm_availability_no_network():
    # LiteLLM availability must be offline
    provider = LiteLLMProvider()
    # Just calling is_available shouldn't trigger anything network
    assert not provider.is_available() # Default disabled

def test_disabled_ollama_direct_calls_fail_closed_without_http():
    provider = OllamaProvider()
    request = InferenceRequest(prompt="offline")
    embedding = EmbeddingRequest(texts=["offline"])

    with patch.object(provider, "is_available", return_value=False), \
         patch("httpx.post") as mock_post, \
         patch("httpx.stream") as mock_stream:
        with pytest.raises(RuntimeError, match="disabled or unavailable"):
            provider.complete(request)
        with pytest.raises(RuntimeError, match="disabled or unavailable"):
            provider.embed(embedding)
        with pytest.raises(RuntimeError, match="disabled or unavailable"):
            list(provider.stream(request))

        mock_post.assert_not_called()
        mock_stream.assert_not_called()

def test_disabled_litellm_direct_calls_fail_closed_without_import_call():
    provider = LiteLLMProvider()
    request = InferenceRequest(prompt="offline")
    embedding = EmbeddingRequest(texts=["offline"])
    fake_litellm = MagicMock()

    with patch.object(provider, "is_available", return_value=False), \
         patch.dict(sys.modules, {"litellm": fake_litellm}):
        with pytest.raises(RuntimeError, match="disabled or unavailable"):
            provider.complete(request)
        with pytest.raises(RuntimeError, match="disabled or unavailable"):
            provider.embed(embedding)
        with pytest.raises(RuntimeError, match="disabled or unavailable"):
            list(provider.stream(request))

    fake_litellm.completion.assert_not_called()
    fake_litellm.embedding.assert_not_called()

def test_explicit_probe_behavior():
    manager = OllamaManager()
    manager._enabled = True

    with patch("httpx.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        # probe is allowed to call when enabled
        assert manager.probe_health() == "ready"
        mock_get.assert_called_once()

def test_provider_failures_do_not_leak_secrets(caplog):
    # If a provider raises an exception with a secret, the router must not log it.
    router = InferenceRouter()
    req = InferenceRequest(prompt="test", sequence_id="test_seq_123")

    provider_mock = MagicMock()
    provider_mock.name = "mock_failing_provider"
    provider_mock.is_available.return_value = True

    class SecretException(Exception):
        def __str__(self):
            return "Failed with secret key sk-12345 and prompt 'test'"

    provider_mock.complete.side_effect = SecretException("secret error")

    router._providers = [provider_mock]
    router.complete(req)

    # Check that "sk-12345" did not leak into logs
    for record in caplog.records:
        assert "sk-12345" not in record.message
        assert "SecretException" in record.message # Type is logged instead
