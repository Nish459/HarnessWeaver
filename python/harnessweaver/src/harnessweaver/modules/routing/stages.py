"""The built-in routing stages: ``rules``, ``lexical``, ``semantic`` and ``llm`` (DESIGNS No. 19).

A stage answers a ``DecisionRequest`` with a ``Decision``: exact, probabilistic
with a confidence, or abstain. The cascade decides whether the answer is
confident enough (ADR-0029). Stage reasons name rules, options and scores, never
the request's text (R9).
"""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from harnessweaver.core.context import current_run
from harnessweaver.core.decisions import Decision, DecisionRequest
from harnessweaver.core.errors import (
    ExpressionError,
    ExpressionSyntaxError,
    ProviderError,
    SpecError,
)
from harnessweaver.core.expr import Expression, compile_expression
from harnessweaver.core.messages import Message, ModelRequest
from harnessweaver.core.plugins import provider
from harnessweaver.core.ports import Embedder
from harnessweaver.core.text import cosine, hashing_embedding, lexical_similarity
from harnessweaver.spec.yaml import load_yaml_file

__all__ = [
    "RULE_VARIABLES",
    "HashingConfig",
    "HashingEmbedder",
    "LexicalConfig",
    "LexicalDecider",
    "LlmDecider",
    "LlmDeciderConfig",
    "RouteRule",
    "RulesConfig",
    "RulesDecider",
    "SemanticConfig",
    "SemanticDecider",
]

RULE_VARIABLES: Final = frozenset({"text", "state", "options", "router"})
"""Names a routing rule's ``when`` may use."""


class _Config(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _from_file(path: str | None, key: str) -> Any:
    if path is None:
        return None
    document = load_yaml_file(Path(path))
    if not isinstance(document, dict) or key not in document:
        raise SpecError(f"{path} must be a map with {key!r}")
    return document[key]  # pyright: ignore[reportUnknownVariableType]


# --- rules ------------------------------------------------------------------------------------


class RouteRule(_Config):
    id: str | None = None
    when: str = Field(description="cel-lite predicate over text, state, options and router.")
    choice: str
    reason: str | None = None


class RulesConfig(_Config):
    rules: tuple[RouteRule, ...] = ()
    file: str | None = Field(default=None, description="A YAML file with a 'rules' list.")


@provider(
    port="Decider",
    name="rules",
    config=RulesConfig,
    deterministic=True,
    latency_class="fast",
    sample={"rules": [{"when": "text.contains('refund')", "choice": "billing"}]},
)
class RulesDecider:
    """The first rule whose ``when`` is true decides, exactly; otherwise it abstains.

    Raises:
        SpecError: At construction, for a rule that doesn't compile.
    """

    def __init__(self, config: RulesConfig) -> None:
        listed = [*config.rules]
        loaded = _from_file(config.file, "rules")
        if loaded is not None:
            listed += [RouteRule.model_validate(item) for item in loaded]
        self.rules: list[tuple[RouteRule, Expression]] = []
        for index, rule in enumerate(listed):
            try:
                expression = compile_expression(rule.when, declared=RULE_VARIABLES)
            except ExpressionSyntaxError as exc:
                raise SpecError(f"routing rule {rule.id or index}: {exc.message}") from None
            self.rules.append((rule, expression))

    @property
    def choices(self) -> set[str]:
        return {rule.choice for rule, _ in self.rules}

    async def __call__(self, request: DecisionRequest) -> Decision:
        variables: dict[str, JsonValue] = {
            "text": request.text or "",
            "state": request.state,
            "options": list(request.options),
            "router": request.router,
        }
        unchecked = 0
        for index, (rule, expression) in enumerate(self.rules):
            try:
                matched = expression.evaluate_bool(variables)
            except ExpressionError:
                unchecked += 1
                continue
            if matched:
                reason = rule.reason or f"rule {rule.id or index + 1}"
                return Decision.exact(rule.choice, reason=reason)
        extra = f" ({unchecked} couldn't be checked)" if unchecked else ""
        return Decision.abstain(reason=f"no rule matched{extra}")


# --- lexical and semantic ---------------------------------------------------------------------


class LexicalConfig(_Config):
    utterances: dict[str, tuple[str, ...]] = Field(
        default_factory=dict[str, tuple[str, ...]], description="Option -> example texts."
    )
    file: str | None = Field(default=None, description="A YAML file with an 'utterances' map.")


def _utterances(config: LexicalConfig) -> dict[str, tuple[str, ...]]:
    found = {option: tuple(texts) for option, texts in config.utterances.items()}
    loaded = _from_file(config.file, "utterances")
    if loaded is not None:
        if not isinstance(loaded, dict):
            raise SpecError(f"{config.file}: utterances must map options to lists of texts")
        for option, texts in loaded.items():  # pyright: ignore[reportUnknownVariableType]
            found[str(option)] = (*found.get(str(option), ()), *[str(t) for t in texts])  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
    if not found:
        raise SpecError("a lexical or semantic stage needs utterances")
    return found


def _best(scores: Mapping[str, float], options: Sequence[str]) -> tuple[str | None, float]:
    """The best-scoring option; ties go to the option listed first."""
    best: tuple[str | None, float] = (None, 0.0)
    for option in [*options, *[o for o in scores if o not in options]]:
        score = scores.get(option, 0.0)
        if score > best[1]:
            best = (option, score)
    return best


@provider(
    port="Decider",
    name="lexical",
    config=LexicalConfig,
    deterministic=True,
    latency_class="fast",
    sample={"utterances": {"billing": ["refund my order"], "other": ["hello there"]}},
)
class LexicalDecider:
    """Scores each option by its closest utterance (token cosine); the best one wins,
    with its score as the confidence. No shared words: it abstains."""

    def __init__(self, config: LexicalConfig) -> None:
        self.utterances = _utterances(config)

    @property
    def choices(self) -> set[str]:
        return set(self.utterances)

    async def __call__(self, request: DecisionRequest) -> Decision:
        text = request.text or ""
        scores = {
            option: max(lexical_similarity(text, utterance) for utterance in utterances)
            for option, utterances in self.utterances.items()
            if utterances
        }
        choice, score = _best(scores, request.options)
        if choice is None:
            return Decision.abstain(reason="no utterance shares a word with the text")
        return Decision.probabilistic(choice, round(score, 6), reason=f"closest to {choice}")


class HashingConfig(_Config):
    dims: int = Field(default=256, ge=16, le=8192)


@provider(
    port="Embedder",
    name="semantic.hashing",
    config=HashingConfig,
    deterministic=True,
    latency_class="fast",
)
class HashingEmbedder:
    """A dependency-free embedder: hashed words and character trigrams (ADR-0029)."""

    def __init__(self, config: HashingConfig | None = None) -> None:
        self.dims = (config or HashingConfig()).dims

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [hashing_embedding(text, self.dims) for text in texts]


class SemanticConfig(LexicalConfig):
    encoder: str = Field(default="semantic.hashing", description="The Embedder provider.")


@provider(
    port="Decider",
    name="semantic",
    config=SemanticConfig,
    deterministic=True,
    latency_class="fast",
    sample={"utterances": {"billing": ["refund my order"], "other": ["hello there"]}},
)
class SemanticDecider:
    """Like ``lexical``, but compares embeddings (cosine). The embedder is the built-in
    ``semantic.hashing`` unless ``encoder`` names another, which the harness binds."""

    def __init__(self, config: SemanticConfig) -> None:
        self.config = config
        self.utterances = _utterances(config)
        self.encoder: Embedder = HashingEmbedder()
        self._vectors: dict[str, list[list[float]]] | None = None

    @property
    def choices(self) -> set[str]:
        return set(self.utterances)

    def bind_encoder(self, encoder: Embedder) -> None:
        """Use ``encoder`` (named by ``encoder:``) instead of the built-in one."""
        self.encoder, self._vectors = encoder, None

    async def __call__(self, request: DecisionRequest) -> Decision:
        if self._vectors is None:
            self._vectors = {
                option: await self.encoder.embed(list(texts))
                for option, texts in self.utterances.items()
            }
        (query,) = await self.encoder.embed([request.text or ""])
        scores = {
            option: max(cosine(query, vector) for vector in vectors)
            for option, vectors in self._vectors.items()
            if vectors
        }
        choice, score = _best(scores, request.options)
        if choice is None:
            return Decision.abstain(reason="nothing is similar to the text")
        confidence = round(min(score, 1.0), 6)
        return Decision.probabilistic(choice, confidence, reason=f"closest to {choice}")


# --- llm --------------------------------------------------------------------------------------


class LlmDeciderConfig(_Config):
    model: str | None = Field(default=None, description="Model alias; the default if unset.")
    instructions: str | None = Field(default=None, description="How to choose, for the model.")


@provider(
    port="Decider",
    name="llm",
    config=LlmDeciderConfig,
    deterministic=False,
    latency_class="slow",
)
class LlmDecider:
    """Asks a model to pick an option and say how sure it is. The confidence is the
    model's own and uncalibrated: tune the stage's threshold on a labelled routing set.
    The call is governed and budgeted like any other."""

    def __init__(self, config: LlmDeciderConfig | None = None) -> None:
        self.config = config or LlmDeciderConfig()

    async def __call__(self, request: DecisionRequest) -> Decision:
        ctx = current_run()
        if ctx is None:
            return Decision.abstain(reason="the llm stage needs an active run")
        options = list(request.options)
        schema: dict[str, JsonValue] = {
            "type": "object",
            "properties": {
                "choice": {"enum": [*options, "none"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["choice", "confidence"],
        }
        guidance = f" {self.config.instructions}" if self.config.instructions else ""
        system = (
            "Choose the one option that best fits the user's message, or none. Answer only "
            'with JSON {"choice": ..., "confidence": 0 to 1}. Options: '
            + ", ".join(options)
            + "."
            + guidance
        )
        response = await ctx.generate(
            ModelRequest(
                alias=self.config.model,
                messages=(Message.system(system), Message.user(request.text or "")),
                output_schema=schema,
                temperature=0,
            )
        )
        answer: Any = response.output
        if answer is None:
            try:
                answer = json.loads(response.text)
            except json.JSONDecodeError:
                raise ProviderError("the llm stage got an answer that isn't JSON") from None
        choice = answer.get("choice") if isinstance(answer, dict) else None  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        confidence = answer.get("confidence") if isinstance(answer, dict) else None  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if choice == "none":
            return Decision.abstain(reason="the model chose none")
        if choice not in options or not isinstance(confidence, int | float):
            raise ProviderError("the llm stage got an answer without a valid choice and confidence")
        value = max(0.0, min(float(confidence), 1.0))
        # The model's own explanation may quote the text, so it isn't kept (R9).
        return Decision.probabilistic(str(choice), value, reason=f"the model chose {choice}")  # pyright: ignore[reportUnknownArgumentType]
