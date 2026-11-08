"""LLM client factory: the one place a provider is chosen (D19).

Provider, model ID and SDK version must be part of config_hash (D21).
"""

from __future__ import annotations

from typing import Any

from evalh.core.interfaces import LLMClient


def make_client(cfg: dict[str, Any]) -> LLMClient:
    match cfg["provider"]:
        case "mistral":
            from evalh.infra.llm.mistral import MistralClient

            return MistralClient(model=cfg["id"], api_key=cfg["api_key"])
        case "anthropic":
            raise NotImplementedError("Anthropic adapter is added before final runs (D3)")
        case other:
            raise ValueError(f"unknown LLM provider: {other}")
