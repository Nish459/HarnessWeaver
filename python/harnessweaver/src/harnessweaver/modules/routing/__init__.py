"""The ``routing`` module: cascades of deciders on ``route.decide`` (DESIGNS No. 19).

``routing.<router>`` lists the options and a cascade of stages: the built-in
``rules``, ``lexical``, ``semantic`` and ``llm`` stages, or any ``@hw.decider``.
The first confident stage wins; every stage's answer is traced.
"""

from harnessweaver.core.text import (
    cosine,
    hashing_embedding,
    lexical_similarity,
    tokens,
)
from harnessweaver.modules.routing.cascade import Stage, decide_in_cascade, install_routing
from harnessweaver.modules.routing.stages import (
    HashingEmbedder,
    LexicalDecider,
    LlmDecider,
    RulesDecider,
    SemanticDecider,
)

__all__ = [
    "HashingEmbedder",
    "LexicalDecider",
    "LlmDecider",
    "RulesDecider",
    "SemanticDecider",
    "Stage",
    "cosine",
    "decide_in_cascade",
    "hashing_embedding",
    "install_routing",
    "lexical_similarity",
    "tokens",
]
