"""Cross-encoder re-ranking through a Text Embeddings Inference (TEI) server serving a reranker model.

POST <url>/rerank {"query", "texts", "truncate"} answers [{"index", "score"}], the score a 0-1 relevance of each
text to the query (sigmoid of the cross-encoder logit). The query is sent as it is (no embedding instruction).
"""
from __future__ import annotations

import logging
from collections.abc import Sequence

import requests

logger = logging.getLogger(__name__)


class RerankError(RuntimeError):
    pass


class TEIReranker:
    def __init__(self, url: str, timeout: float = 10.0, session: requests.Session | None = None) -> None:
        self._url = url.rstrip("/") + "/rerank"
        self._timeout = timeout
        self._session = session or requests.Session()

    def rerank(self, query: str, texts: Sequence[str]) -> list[float]:
        """The relevance score of each text, in the order of ``texts``."""
        if not texts:
            return []
        try:
            resp = self._session.post(self._url, json={"query": query, "texts": list(texts), "truncate": True},
                                      timeout=self._timeout)
            resp.raise_for_status()
            ranked = resp.json()
            scores = [0.0] * len(texts)
            for item in ranked:
                scores[int(item["index"])] = float(item["score"])
            if len(ranked) != len(texts):
                raise RerankError(f"reranker returned {len(ranked)} scores for {len(texts)} texts")
            return scores
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
            raise RerankError(str(exc)) from exc
