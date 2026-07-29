"""Optional PydanticAI boundary for typed MarketOS domain agents."""
from __future__ import annotations

import os
from typing import Any

from backend.contracts.adapters import AdapterHealth, AgentProvider


class PydanticAIAgentProvider:
    name = "pydantic-ai"

    def health(self) -> AdapterHealth:
        try:
            import pydantic_ai  # noqa: F401
        except ImportError:
            return AdapterHealth(self.name, configured=False, reachable=False, detail="optional dependency is not installed")
        return AdapterHealth(self.name, configured=True, reachable=True, capabilities=("typed_output", "tools", "mcp", "approval"))

    def create(self, *, name: str, instructions: str, output_type: Any = None) -> Any:
        try:
            from pydantic_ai import Agent
        except ImportError as exc:
            raise RuntimeError("PydanticAI is not installed; install the reviewed optional OSS profile") from exc
        model = os.getenv("MARKETOS_AGENT_MODEL", "openai:gpt-4o-mini")
        kwargs: dict[str, Any] = {"model": model, "instructions": instructions}
        if output_type is not None:
            kwargs["output_type"] = output_type
        agent = Agent(**kwargs)
        setattr(agent, "marketos_agent_name", name)
        return agent


agent_provider: AgentProvider = PydanticAIAgentProvider()
