"""MistralClient tests with a faked SDK. No live API calls (CLAUDE.md)."""

from __future__ import annotations

from types import SimpleNamespace as NS
from typing import Any

import pytest

from evalh.core.schemas import Message, ToolCall, ToolSpec
from evalh.infra.llm.client import make_client
from evalh.infra.llm.mistral import MistralClient, parse_args, to_wire


class FakeChat:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.kwargs: dict[str, Any] = {}

    async def complete_async(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return self.response


def _response(finish: str, content: Any = "", tool_calls: Any = None, usage: Any = None) -> Any:
    msg = NS(content=content, tool_calls=tool_calls)
    return NS(choices=[NS(finish_reason=finish, message=msg)], usage=usage)


def _client(resp: Any) -> tuple[MistralClient, FakeChat]:
    chat = FakeChat(resp)
    return MistralClient(model="devstral-test", sdk=NS(chat=chat)), chat


SPEC = ToolSpec(name="grep", description="search", input_schema={"type": "object"})


async def test_tool_call_parsed_and_request_shape() -> None:
    tc = NS(id="c1", function=NS(name="grep", arguments='{"pattern": "foo"}'))
    usage = NS(prompt_tokens=120, completion_tokens=8)
    client, chat = _client(_response("tool_calls", None, [tc], usage))

    out = await client.complete([Message(role="user", content="find foo")], [SPEC], 512)

    assert out.stop_reason == "tool_use"
    assert out.message.tool_calls == (ToolCall(id="c1", name="grep", args={"pattern": "foo"}),)
    assert out.usage.input_tokens == 120 and out.usage.output_tokens == 8
    assert out.usage.cache_read_tokens == 0
    assert chat.kwargs["tool_choice"] == "auto"
    assert chat.kwargs["max_tokens"] == 512
    assert "temperature" not in chat.kwargs
    assert chat.kwargs["tools"][0]["function"]["name"] == "grep"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("stop", "end_turn"),
        ("length", "max_tokens"),
        ("model_length", "max_tokens"),
        ("something_new", "error"),
    ],
)
async def test_stop_reason_mapping(raw: str, expected: str) -> None:
    client, _ = _client(_response(raw, "done"))
    out = await client.complete([Message(role="user", content="x")], [], 16)
    assert out.stop_reason == expected
    assert out.raw_stop_reason == raw


async def test_chunked_content_and_missing_usage() -> None:
    client, chat = _client(_response("stop", [NS(text="a"), NS(text="b")]))
    out = await client.complete([Message(role="user", content="x")], [], 16)
    assert out.message.content == "ab"
    assert out.usage.input_tokens == 0
    assert chat.kwargs["tools"] is None


def test_parse_args_malformed() -> None:
    assert parse_args({"a": 1}) == {"a": 1}
    assert parse_args('{"a": 1}') == {"a": 1}
    assert parse_args("{bad json") == {"__malformed__": "{bad json"}
    assert parse_args("[1, 2]") == {"__malformed__": "[1, 2]"}


def test_to_wire_tool_and_assistant_messages() -> None:
    tool = to_wire(Message(role="tool", content="r", tool_call_id="c1", tool_name="grep"))
    assert tool == {"role": "tool", "tool_call_id": "c1", "name": "grep", "content": "r"}
    asst = to_wire(
        Message(role="assistant", tool_calls=(ToolCall(id="c1", name="grep", args={"p": 1}),))
    )
    assert asst["tool_calls"][0]["function"]["arguments"] == '{"p": 1}'


def test_factory_unknown_and_anthropic() -> None:
    with pytest.raises(ValueError):
        make_client({"provider": "nope"})
    with pytest.raises(NotImplementedError):
        make_client({"provider": "anthropic"})
