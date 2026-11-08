"""Provider-neutral schemas shared by core, plugins and infra."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

StopReason = Literal["end_turn", "tool_use", "max_tokens", "refusal", "error"]


class ToolSpec(BaseModel, frozen=True):
    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema


class ToolCall(BaseModel, frozen=True):
    id: str
    name: str
    args: dict[str, Any]


class Message(BaseModel, frozen=True):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()  # assistant only
    tool_call_id: str | None = None  # tool only
    tool_name: str | None = None  # tool only


class Usage(BaseModel, frozen=True):
    """Provider-reported usage. Billing only; delivered tokens use the D20 tokenizer."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0  # 0 where the provider has no prompt caching
    cache_write_tokens: int = 0


class Completion(BaseModel, frozen=True):
    message: Message
    stop_reason: StopReason
    raw_stop_reason: str  # provider value, kept for health metrics
    usage: Usage
    latency_s: float = 0.0


class Capabilities(BaseModel, frozen=True):
    prompt_cache: bool
    batch_api: bool
    effort_param: bool
