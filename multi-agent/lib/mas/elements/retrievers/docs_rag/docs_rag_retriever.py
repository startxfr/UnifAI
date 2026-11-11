from typing import Dict, List, Literal, Optional

from mas.elements.retrievers.common.base_retriever import BaseRetriever
from mas.elements.retrievers.common.protocols import RetrievalIdentity
from mas.elements.providers.rag_client.config import RagProviderConfig
from mas.elements.providers.rag_client.rag_provider_factory import RagProviderFactory
from mas.core.identity_forwarding import IdentityForwarder


RRF_K = 60  # reciprocal rank fusion constant (Cormack et al.): a rank counts 1 / (RRF_K + rank)


def _rrf(per_type: List[list], top_k: int) -> list:
    """Merge the ranked match lists of several source types by rank only. The score of a search is normalised on
    the candidates of that search (hybrid DBSF), so the scores of two source types are not on one scale and a sort
    by score lets one type outrank the other (R-551)."""
    scored = [(1.0 / (RRF_K + rank), m) for matches in per_type for rank, m in enumerate(matches, 1)]
    return [m for _, m in sorted(scored, key=lambda x: x[0], reverse=True)][:top_k]


class DocsRagRetriever(BaseRetriever):
    """
    Retrieves document passages via RAG vector database.

    Depends on ``RetrievalIdentity`` (Protocol) for access control —
    knows nothing about ``ExecutionContext`` or holders.
    """

    def __init__(
            self,
            top_k_results: int,
            threshold: float,
            timeout: float = 30.0,
            docs: Optional[List[Dict]] = None,
            tags: Optional[List[str]] = None,
            identity: Optional[RetrievalIdentity] = None,
            forwarder: Optional[IdentityForwarder] = None,
            source_type: str = "DOCUMENT",
            extra_source_types: Optional[List[str]] = None,
            source_merge: Literal["score", "rrf"] = "score",
    ):
        self.threshold = threshold
        self.docs = docs
        self.tags = tags
        self._identity = identity
        self._forwarder = forwarder
        self._source_type = source_type
        self._source_types = [source_type] + [
            s for s in (extra_source_types or []) if s != source_type
        ]
        self._source_merge = source_merge
        self._top_k = top_k_results
        config = RagProviderConfig(
            top_k=top_k_results,
            timeout=timeout,
        )
        factory = RagProviderFactory()
        self._provider = factory.create(config)

    def retrieve(self, query: str) -> List[dict]:
        user_id = self._identity.identity_id if self._identity else ""
        doc_ids = [doc['id'] for doc in self.docs] if self.docs else None

        headers = self._forwarder.headers(forward_token=True) if self._forwarder else None
        per_type = []
        for source_type in self._source_types:
            response = self._provider.query(
                query=query,
                doc_ids=doc_ids,
                tags=self.tags,
                authenticated_user=user_id,
                extra_headers=headers,
                source_type=source_type,
            )
            per_type.append([m for m in response.matches if m.score >= self.threshold])

        if len(self._source_types) == 1:
            matches = per_type[0]
        elif self._source_merge == "rrf":
            matches = _rrf(per_type, self._top_k)
        else:
            matches = sorted((m for lst in per_type for m in lst), key=lambda m: m.score, reverse=True)[:self._top_k]
        return [match.model_dump() for match in matches]
