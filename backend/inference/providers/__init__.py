"""backend.inference.providers — concrete inference provider implementations."""
from .base      import BaseProvider
from .mock      import MockProvider
from .anthropic import AnthropicProvider
from .openai    import OpenAIProvider
from .ollama    import OllamaProvider
from .vllm      import VLLMProvider
from .airllm    import AirLLMProvider
from .litellm   import LiteLLMProvider

__all__ = [
    "BaseProvider",
    "MockProvider",
    "AnthropicProvider",
    "OpenAIProvider",
    "OllamaProvider",
    "VLLMProvider",
    "AirLLMProvider",
    "LiteLLMProvider",
]

# Registry: name → class  (used by router to instantiate providers by name)
REGISTRY: dict[str, type[BaseProvider]] = {
    "anthropic": AnthropicProvider,
    "openai":    OpenAIProvider,
    "ollama":    OllamaProvider,
    "vllm":      VLLMProvider,
    "airllm":    AirLLMProvider,
    "litellm":   LiteLLMProvider,
    "mock":      MockProvider,
}
