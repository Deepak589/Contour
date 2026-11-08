"""Small protocols the core depends on. Concrete classes live in plugins/ and infra/."""

from __future__ import annotations

from typing import Protocol

from evalh.core.schemas import Capabilities, Completion, Message, ToolSpec


class LLMClient(Protocol):
    """One adapter per provider (D19). Callers see only neutral types."""

    provider: str
    model: str
    caps: Capabilities

    async def complete(
        self, messages: list[Message], tools: list[ToolSpec], max_output_tokens: int
    ) -> Completion: ...
