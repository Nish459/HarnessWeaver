"""Text scoring shared by the ``lexical`` and ``semantic`` stages and the ``memory``
context provider. It is part of the contract (fixtures suite ``routing``, ADR-0029):

* **Tokens** are runs of letters and digits, lowercased; everything else separates.
* **Lexical similarity** is the cosine of two texts' token counts.
* **Hashing embeddings** (``semantic.hashing``): each token adds 1, and each
  character trigram of ``^token$`` adds 0.5, at index ``h % dims`` with the sign
  ``+`` when bit 16 of ``h`` is 0 and ``-`` otherwise, where ``h`` is the 32-bit
  FNV-1a hash of the UTF-8 bytes of ``"t:" + token`` or ``"c:" + trigram``. The
  vector is then scaled to length 1 (all zeros stays zeros).
"""

import math
import re
from collections import Counter
from collections.abc import Sequence
from typing import Final

__all__ = ["cosine", "fnv1a32", "hashing_embedding", "lexical_similarity", "tokens"]

_TOKEN = re.compile(r"[^\W_]+")
_FNV_OFFSET: Final = 0x811C9DC5
_FNV_PRIME: Final = 0x01000193


def tokens(text: str) -> list[str]:
    """The text's tokens, in order."""
    return _TOKEN.findall(text.lower())


def lexical_similarity(a: str, b: str) -> float:
    """Cosine of the two texts' token counts: 1.0 for the same words, 0.0 for none shared."""
    first, second = Counter(tokens(a)), Counter(tokens(b))
    if not first or not second:
        return 0.0
    dot = sum(count * second[token] for token, count in first.items())
    norm = math.sqrt(sum(c * c for c in first.values())) * math.sqrt(
        sum(c * c for c in second.values())
    )
    return dot / norm


def fnv1a32(data: bytes) -> int:
    """32-bit FNV-1a."""
    value = _FNV_OFFSET
    for byte in data:
        value = ((value ^ byte) * _FNV_PRIME) & 0xFFFFFFFF
    return value


def hashing_embedding(text: str, dims: int = 256) -> list[float]:
    """A deterministic bag-of-words-and-trigrams vector of length ``dims``."""
    vector = [0.0] * dims
    for token in tokens(text):
        marked = f"^{token}$"
        features = [(f"t:{token}", 1.0)]
        features += [(f"c:{marked[i : i + 3]}", 0.5) for i in range(len(marked) - 2)]
        for feature, weight in features:
            h = fnv1a32(feature.encode("utf-8"))
            vector[h % dims] += weight if (h >> 16) & 1 == 0 else -weight
    length = math.sqrt(sum(v * v for v in vector))
    return [v / length for v in vector] if length else vector


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity; 0.0 when either vector is all zeros."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0
