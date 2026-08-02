"""Optional low-risk Ollama enrichment for research artifacts."""
from __future__ import annotations

import json
from typing import Any


def summarize_dossier(dossier: dict[str, Any]) -> dict[str, Any] | None:
    """Ask local Ollama for a concise hypothesis summary, never a decision.

    Failure returns ``None``. The caller must retain the original dossier and
    treat this output as an untrusted, human-reviewable annotation.
    """
    try:
        from backend.ollama_manager import OllamaManager
        manager = OllamaManager()
        if not manager.is_healthy():
            return None
        from backend.inference.models.inference_request import InferenceRequest
        from backend.inference.providers.ollama import OllamaProvider
        prompt = "Summarize this commerce research dossier in JSON with keys risks, hypotheses, questions. Do not recommend launching. Dossier:\n" + json.dumps(dossier, default=str)[:12000]
        response = OllamaProvider().complete(InferenceRequest(prompt=prompt, max_tokens=600, temperature=0.1))
        text = response.content.strip()
        if text.startswith("```"):
            text = text.strip("`").replace("json", "", 1).strip()
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except Exception:
        return None
