"""Mistral adapter: development backend (D19). Never used for reported results."""

from __future__ import annotations

import json
import time
from typing import Any

from evalh.core.schemas import (
    Capabilities,
    Completion,
    Message,
    StopReason,
    ToolCall,
    ToolSpec,
    Usage,
)

_STOP: dict[str, StopReason] = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
    "model_length": "max_tokens",
    "error": "error",
}


def to_wire(m: Message) -> dict[str, Any]:
    if m.role == "tool":
        return {
            "role": "tool",
            "tool_call_id": m.tool_call_id,
            "name": m.tool_name,
            "content": m.content,
        }
    d: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_calls:
        d["tool_calls"] = [
            {
                "id": t.id,
                "type": "function",
                "function": {"name": t.name, "arguments": json.dumps(t.args)},
            }
            for t in m.tool_calls
        ]
    return d


def parse_args(raw: Any) -> dict[str, Any]:
    """Args arrive as a dict or a JSON string; small models emit bad JSON."""
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"__malformed__": str(raw)}
    return parsed if isinstance(parsed, dict) else {"__malformed__": str(raw)}


def _text(content: Any) -> str:
    """Content is a str, a list of chunks, or unset."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(getattr(c, "text", "") or "" for c in content)
    return ""


class MistralClient:
    provider = "mistral"
    caps = Capabilities(prompt_cache=False, batch_api=True, effort_param=False)

    def __init__(self, model: str, api_key: str = "", sdk: Any = None) -> None:
        self.model = model
        if sdk is None:
            from mistralai.client import Mistral

            sdk = Mistral(api_key=api_key)
        self._sdk = sdk

    async def complete(
        self, messages: list[Message], tools: list[ToolSpec], max_output_tokens: int
    ) -> Completion:
        t0 = time.perf_counter()
        r = await self._sdk.chat.complete_async(
            model=self.model,
            messages=[to_wire(m) for m in messages],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in tools
            ]
            or None,
            tool_choice="auto",
            max_tokens=max_output_tokens,
        )
        latency = time.perf_counter() - t0
        ch = r.choices[0]
        msg = ch.message
        calls = tuple(
            ToolCall(id=tc.id or "", name=tc.function.name, args=parse_args(tc.function.arguments))
            for tc in ((msg.tool_calls if msg else None) or [])
        )
        raw = str(ch.finish_reason)
        usage = r.usage
        return Completion(
            message=Message(
                role="assistant", content=_text(msg.content if msg else None), tool_calls=calls
            ),
            stop_reason=_STOP.get(raw, "error"),
            raw_stop_reason=raw,
            usage=Usage(
                input_tokens=(usage.prompt_tokens or 0) if usage else 0,
                output_tokens=(usage.completion_tokens or 0) if usage else 0,
            ),
            latency_s=latency,
        )
