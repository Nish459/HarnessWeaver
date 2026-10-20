"""Pydantic AI models whose every request is one governed harness model call.

* :class:`HarnessModel` answers from the harness's own model provider (``models``
  in the spec: aliases, prices and allow-lists apply), so a gateway owns retries
  and keys (R5, S1).
* :class:`GovernedModel` wraps the agent's own model, as ``harness.wrap(agent)``
  does: the request goes through the harness, and the wrapped model answers it.

Both fire ``model.before`` and ``model.after``, check budgets, record the answer
for replays and trace the call (DESIGNS No. 16). Streaming through them is
*planned*; until then a streamed run raises rather than running ungoverned (R4).
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import RunContext as AgentContext

import harnessweaver as hw
from harnessweaver.adapters import CallProvider
from harnessweaver_pydantic_ai.convert import (
    apply_request,
    from_neutral,
    patch_text,
    to_neutral,
    to_request,
)

__all__ = ["STREAMING", "GovernedModel", "HarnessModel"]

STREAMING = (
    "streaming a governed Pydantic AI agent isn't supported yet (planned); use run() or iter()"
)


def _no_streaming() -> hw.errors.SpecError:
    return hw.errors.SpecError(STREAMING)


class HarnessModel(Model):
    """A Pydantic AI model answered by the harness's model provider.

    Structured output is asked for with the neutral request's ``output_schema``,
    so the agent's output types use Pydantic AI's native output mode by default.
    """

    def __init__(self, run: hw.RunContext) -> None:
        profile = ModelProfile(
            supports_json_schema_output=True,
            supports_json_object_output=True,
            default_structured_output_mode="native",
        )
        super().__init__(profile=profile)
        self.run = run

    @property
    def model_name(self) -> str:
        return "harnessweaver"

    @property
    def system(self) -> str:
        return "harnessweaver"

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        settings, params = self.prepare_request(model_settings, model_request_parameters)
        request, _ = to_request(messages, settings, params)
        return from_neutral(await self.run.generate(request), params)

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: AgentContext[Any] | None = None,
    ) -> AsyncGenerator[StreamedResponse]:
        raise _no_streaming()
        yield  # pragma: no cover


class GovernedModel(WrapperModel):
    """The agent's own model, with each request made through the harness.

    Redactions by ``model.before`` middleware reach the request the model gets,
    and changes ``model.after`` or output middleware make to the answer's text
    reach the agent. During a replay the recording answers instead (ADR-0035).
    """

    def __init__(self, wrapped: Model, run: hw.RunContext) -> None:
        super().__init__(wrapped)
        self.run = run

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        request, where = to_request(messages, model_settings, model_request_parameters)
        answers: list[ModelResponse] = []

        async def call(sent: hw.ModelRequest) -> hw.ModelResponse:
            final, params = apply_request(
                messages, model_request_parameters, where, request.messages, sent.messages
            )
            answer = await self.wrapped.request(final, model_settings, params)
            answers.append(answer)
            return to_neutral(answer)

        response = await self.run.generate(request, provider=CallProvider(call))
        if not answers:  # a replay: the recording answered
            return from_neutral(response, model_request_parameters)
        return patch_text(answers[-1], response.text)

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: AgentContext[Any] | None = None,
    ) -> AsyncGenerator[StreamedResponse]:
        raise _no_streaming()
        yield  # pragma: no cover
