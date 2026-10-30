"""Sparse (lexical) vectors for Qdrant hybrid search.

A hashing BM25 encoder: no model download, no new dependency, works offline.
Documents get BM25 term-frequency weights (saturation k1, no length
normalisation); Qdrant's ``Modifier.IDF`` on the sparse vector applies the
inverse document frequency server-side from the collection's own statistics.
Queries get weight 1.0 per distinct term, so the score is the BM25 sum over
matching terms.

Version 2 (BM25 proper) drops English and French stop words on both sides and normalises a document's term
frequencies by its length (b, against a fixed average length): a long chunk that repeats a common term no longer
outranks a short chunk that defines it. Its vectors are not comparable with version 1, so it lives in its own
collection (see QdrantVectorRepository).

Tokens are Unicode word characters, lower-cased with accents folded
("Procédure" and "procedure" match), so identifiers and product names that
dense embeddings blur (e.g. ``ERR_TLS_CERT``, ``oc adm``) still match exactly.
"""
from __future__ import annotations

import re
import unicodedata
import zlib
from collections import Counter
from dataclasses import dataclass

_TOKEN = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class SparseVector:
    indices: list[int]
    values: list[float]


def tokenize(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", text.lower())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return [t for t in _TOKEN.findall(folded) if len(t) > 1 or t.isdigit()]


def _index(token: str) -> int:
    # Stable across processes and Python versions (unlike hash()); 31-bit as Qdrant indices are uint32.
    return zlib.crc32(token.encode("utf-8")) & 0x7FFFFFFF


STOP_WORDS = frozenset("""
a about above after again against all am an and any are as at be because been before being below between both but
by can could did do does doing down during each few for from further had has have having he her here hers herself
him himself his how i if in into is it its itself just me more most my myself no nor not now of off on once only or
other our ours ourselves out over own same she should so some such than that the their theirs them themselves then
there these they this those through to too under until up very was we were what when where which while who whom why
will with would you your yours yourself yourselves
au aux avec ce ces cet cette dans de des du elle en est et il ils je la le les leur leurs lui ma mais me mes moi mon
ne nos notre nous on ou par pas pour qu que qui sa se ses son sont sur ta te tes toi ton tu un une vos votre vous
""".split())


class HashingBM25Encoder:
    """BM25-style sparse encoder over hashed tokens (version 1: no stop words, no length normalisation)."""

    def __init__(self, k1: float = 1.2, version: int = 1, b: float = 0.75, avg_doc_tokens: float = 150.0) -> None:
        if version not in (1, 2):
            raise ValueError(f"sparse encoder version must be 1 or 2, got {version}")
        self._k1 = k1
        self.version = version
        self._b = b if version == 2 else 0.0
        self._avg = avg_doc_tokens

    def _tokens(self, text: str) -> list[str]:
        tokens = tokenize(text)
        return [t for t in tokens if t not in STOP_WORDS] if self.version == 2 else tokens

    def encode_document(self, text: str) -> SparseVector:
        tokens = self._tokens(text)
        counts = Counter(_index(t) for t in tokens)
        norm = self._k1 * (1 - self._b + self._b * len(tokens) / self._avg)
        return self._vector({i: tf * (self._k1 + 1) / (tf + norm) for i, tf in counts.items()})

    def encode_query(self, text: str) -> SparseVector:
        return self._vector({_index(t): 1.0 for t in self._tokens(text)})

    @staticmethod
    def _vector(weights: dict[int, float]) -> SparseVector:
        indices = sorted(weights)
        return SparseVector(indices=indices, values=[float(weights[i]) for i in indices])
