# Local Inference Safety Boundary

## Overview
MarketOS enforces a strict offline-by-default local inference boundary. Local model providers (Ollama, LiteLLM) are strictly configured to not start daemon processes, pull models, or emit unannounced network probes when initializing the router.

## Activation
By default, `OllamaProvider` and `LiteLLMProvider` are disabled. They will not execute API calls or check endpoints.
To explicitly opt in to local execution:
- Set `OLLAMA_ENABLED=true`
- Set `LITELLM_ENABLED=true`
Only then will the providers be considered `available`.

## Offline Readiness Check
The `is_available()` check for both providers is strictly an offline configuration check. It does not probe `http://localhost:11434/api/tags` or call any external endpoints.

## Explicit Health Probing
If a live status is required (e.g. by an operator running diagnostics), they can call `provider.probe()` which explicitly executes the network request to verify actual local process health.

## Bounded Lifecycle
Operations such as starting the Ollama daemon (`ensure_running`) or pulling a model (`pull_model`) are disabled by default. If enabled via `OLLAMA_AUTO_START=true`, they strictly run within defined timeout boundaries. They do not have unbounded retry loops.

## Data Privacy
Failures within any provider fallback are safely logged using their exception type. We strictly omit recording the exception message into telemetry or the logger to prevent raw prompts, credentials, or completion outputs from leaking into execution logs.
