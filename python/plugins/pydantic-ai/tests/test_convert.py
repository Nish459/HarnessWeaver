"""Pydantic AI messages to neutral contracts and back (R7)."""

from typing import Any

import pytest
from pydantic_ai.messages import (
    ImageUrl,
    InstructionPart,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    SystemPromptPart,
    TextContent,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.output import OutputObjectDefinition
from pydantic_ai.tools import ToolDefinition

import harnessweaver as hw
from harnessweaver.testing import harness_for_test
from harnessweaver_pydantic_ai.capability import HarnessCapability, _retyped  # pyright: ignore[reportPrivateUsage]
from harnessweaver_pydantic_ai.convert import (
    apply_request,
    from_neutral,
    patch_text,
    to_json,
    to_neutral,
    to_request,
    user_text,
)
from harnessweaver_pydantic_ai.model import HarnessModel

IMAGE = ImageUrl(url="https://example.com/cat.png")
ANSWER = {"type": "object", "properties": {"category": {"type": "string"}}}


def tool(name: str, **fields: Any) -> ToolDefinition:
    return ToolDefinition(name=name, parameters_json_schema=ANSWER, **fields)


HISTORY = [
    ModelRequest(
        parts=[
            SystemPromptPart("Be brief."),
            UserPromptPart(["Look at", TextContent("this"), IMAGE]),
        ],
        instructions="Help the customer.",
    ),
    ModelResponse(
        parts=[TextPart("Checking."), ToolCallPart("lookup", {"id": 7}, tool_call_id="c1")]
    ),
    ModelRequest(
        parts=[
            ToolReturnPart("lookup", {"found": True}, tool_call_id="c1"),
            RetryPromptPart("try again", tool_name="lookup", tool_call_id="c2"),
            RetryPromptPart("be clearer"),
        ]
    ),
]


def test_a_history_becomes_neutral_messages() -> None:
    params = ModelRequestParameters(function_tools=[tool("lookup", description="Find it.")])
    request, where = to_request(HISTORY, {"temperature": 0.2, "max_tokens": 50}, params)
    shown = [(m.role.value, m.content, m.tool_call_id) for m in request.messages]
    assert shown[:4] == [
        ("system", "Help the customer.", None),  # instructions from the history
        ("system", "Be brief.", None),
        ("user", "Look at\nthis", None),  # the image isn't part of the neutral view
        ("assistant", "Checking.", None),
    ]
    assert shown[4][0] == "tool"
    assert '"found":true' in shown[4][1].replace(" ", "")
    assert shown[5][0] == "tool"
    assert shown[5][2] == "c2"
    assert shown[6][0] == "user"
    assert "be clearer" in shown[6][1]
    assert request.messages[3].tool_calls == (
        hw.ToolCall(id="c1", name="lookup", arguments={"id": 7}),
    )
    assert where == ["instructions", (0, 0), (0, 1), None, (2, 0), (2, 1), (2, 2)]
    assert (request.temperature, request.max_tokens) == (0.2, 50)
    assert [t.name for t in request.tools] == ["lookup"]
    assert request.tools[0].description == "Find it."


@pytest.mark.parametrize(
    ("params", "schema", "tools"),
    [
        (ModelRequestParameters(output_mode="text"), None, []),
        (
            ModelRequestParameters(
                output_mode="native", output_object=OutputObjectDefinition(json_schema=ANSWER)
            ),
            ANSWER,
            [],
        ),
        (
            ModelRequestParameters(output_mode="tool", output_tools=[tool("final_result")]),
            ANSWER,
            [],
        ),
        (
            ModelRequestParameters(output_mode="tool", output_tools=[tool("a"), tool("b")]),
            None,
            ["a", "b"],
        ),
    ],
)
def test_output_is_asked_for_by_schema_or_by_tools(
    params: ModelRequestParameters, schema: Any, tools: list[str]
) -> None:
    request, _ = to_request([ModelRequest(parts=[UserPromptPart("hi")])], None, params)
    assert request.output_schema == schema
    assert [t.name for t in request.tools] == tools


def test_changed_text_is_written_back_to_this_request_only() -> None:
    params = ModelRequestParameters(instruction_parts=[InstructionPart(content="Help.")])
    request, where = to_request(HISTORY, None, params)
    edited = [m.model_copy(update={"content": m.content.upper()}) for m in request.messages]
    messages, changed = apply_request(HISTORY, params, where, request.messages, edited)
    assert changed.instruction_parts == [InstructionPart(content="HELP.")]
    first = messages[0]
    assert isinstance(first, ModelRequest)
    system, prompt = first.parts
    assert isinstance(system, SystemPromptPart)
    assert system.content == "BE BRIEF."
    assert isinstance(prompt, UserPromptPart)
    assert prompt.content == ["LOOK AT\nTHIS", IMAGE]
    assert messages[1] is HISTORY[1]  # a model's own answer is never rewritten
    original = HISTORY[0]
    assert isinstance(original, ModelRequest)
    assert original.parts[0] == SystemPromptPart("Be brief.", timestamp=system.timestamp)


def test_answers_convert_both_ways() -> None:
    answer = ModelResponse(
        parts=[TextPart("a"), TextPart("b"), ToolCallPart("lookup", '{"id": 1}')]
    )
    neutral = to_neutral(answer)
    assert (neutral.text, neutral.tool_calls[0].arguments) == ("ab", {"id": 1})
    patched = patch_text(answer, "c")
    assert [p.content for p in patched.parts if isinstance(p, TextPart)] == ["c"]
    assert patch_text(answer, "ab") is answer
    only_call = ModelResponse(parts=[ToolCallPart("lookup", {})])
    assert isinstance(patch_text(only_call, "x").parts[0], TextPart)


def args(response: ModelResponse) -> tuple[str, Any]:
    (part,) = response.parts
    assert isinstance(part, ToolCallPart)
    return part.tool_name, part.args


def test_harness_answers_fit_the_agents_output_mode() -> None:
    boxed = ModelRequestParameters(
        output_mode="tool", output_tools=[tool("final_result", outer_typed_dict_key="response")]
    )
    assert args(from_neutral(hw.ModelResponse(output=42), boxed)) == (
        "final_result",
        {"response": 42},
    )
    plain = ModelRequestParameters(output_mode="tool", output_tools=[tool("final_result")])
    assert args(from_neutral(hw.ModelResponse(output={"a": 1}), plain)) == (
        "final_result",
        {"a": 1},
    )
    assert args(from_neutral(hw.ModelResponse(output=[1]), plain))[1] == {"response": [1]}
    native = ModelRequestParameters(output_mode="native")
    assert from_neutral(hw.ModelResponse(output={"a": 1}), native).parts == [TextPart('{"a": 1}')]
    calls = hw.ModelResponse(tool_calls=(hw.ToolCall(id="t1", name="x", arguments={}),))
    (call,) = from_neutral(calls, native).parts
    assert isinstance(call, ToolCallPart)
    assert call.tool_call_id == "t1"


def test_values_and_outputs() -> None:
    assert user_text("plain") == "plain"
    assert to_json(object()) == "object"  # what JSON can't hold is named, not shown
    assert _retyped("a", {"b": 1}) == '{"b": 1}'  # a text output stays text
    assert _retyped(hw.Usage(), {"input_tokens": 3}) == hw.Usage(input_tokens=3)
    assert _retyped(7, 8) == 8


@pytest.mark.anyio
async def test_streaming_and_bare_use_are_refused() -> None:
    harness = harness_for_test({})
    async with harness.session() as session:
        model = HarnessModel(session.run_context)
        assert (model.model_name, model.system) == ("harnessweaver", "harnessweaver")
        with pytest.raises(hw.errors.SpecError, match="streaming"):
            async with model.request_stream([], None, ModelRequestParameters()):
                pass  # pragma: no cover
    with pytest.raises(hw.errors.SpecError, match="governs runs started by"):
        await HarnessCapability().before_model_request(None, None)  # type: ignore[arg-type]
