"""Ranking of hybrid search: BM25 v2, score fusion, query instruction and the index migration."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
import qdrant_client

from core.vector.domain.model import VectorChunk
from infrastructure.embedding.embedding_generator import DefaultEmbeddingGenerator
from infrastructure.qdrant.mirrored_vector_repository import MirroredVectorRepository
from infrastructure.qdrant.qdrant_vector_repository import QdrantVectorRepository
from infrastructure.qdrant.sparse_encoder import HashingBM25Encoder

pytestmark = pytest.mark.unit

QUESTION = "What is a namespace in OpenShift?"
DEFINITION = "A project is a Kubernetes namespace with additional annotations."
# An installation guide: long, repeats the common terms, does not answer.
INSTALL = " ".join(["Install OpenShift on the cluster and create the namespace for the installer in OpenShift."] * 12)


@pytest.fixture
def client():
    return qdrant_client.QdrantClient(":memory:")


def repo(client, version, name="web", fusion="dbsf"):
    r = QdrantVectorRepository(collection_name=name, embedding_dim=2, url="http://unused", hybrid=True,
                               client=client, sparse_version=version, fusion=fusion)
    r.initialize()
    return r


def store(r):
    # Same dense vector for both: only the sparse side decides.
    r.store([VectorChunk(text=t, embedding=[1.0, 0.0], metadata={"source_id": sid, "chunk_index": 0, "owner_id": "a"})
             for sid, t in (("def", DEFINITION), ("install", INSTALL))])


def test_v2_drops_stop_words_and_normalises_by_length():
    v1, v2 = HashingBM25Encoder(version=1), HashingBM25Encoder(version=2)
    assert len(v2.encode_query(QUESTION).indices) == 2  # namespace, openshift
    assert len(v1.encode_query(QUESTION).indices) == 5  # what, is, namespace, in, openshift (single letters dropped)
    ns = v2.encode_query("namespace").indices[0]

    def weight(vec):
        return dict(zip(vec.indices, vec.values))[ns]
    short, long_ = v2.encode_document("namespace isolation"), v2.encode_document("namespace " + "word " * 600)
    assert weight(short) > weight(long_), "a long chunk weighs its terms less"
    # Version 1 is unchanged: no length normalisation.
    assert v1.encode_document("namespace").values == v1.encode_document("namespace " + "word " * 600).values[:1]


def test_v2_narrows_the_gap_between_a_short_definition_and_a_long_guide():
    """BM25 alone still rewards the guide that repeats the terms (saturated, not inverted): the reranker and the
    query instruction decide; v2 only stops stop words and raw length from adding to the guide's lead."""
    def lead(version):
        enc = HashingBM25Encoder(version=version)
        q = set(enc.encode_query(QUESTION).indices)

        def score(text):
            d = enc.encode_document(text)
            return sum(v for i, v in zip(d.indices, d.values) if i in q)
        return score(INSTALL) / score(DEFINITION)
    assert lead(2) < lead(1)


def test_collections_are_named_by_sparse_version(client):
    assert repo(client, 1)._collection_name == "web_hybrid"
    assert repo(client, 2)._collection_name == "web_hybrid_v2"


def test_dbsf_scores_are_not_ranks(client):
    r = repo(client, 2)
    store(r)
    scores = [h.score for h in r.search([1.0, 0.0], top_k=2, query_text=QUESTION)]
    assert scores != [0.5, 1 / 3], "DBSF fuses scores, RRF would give 1/(rank+1)"
    with pytest.raises(ValueError):
        QdrantVectorRepository(collection_name="x", embedding_dim=2, url="http://unused", hybrid=True,
                               client=client, fusion="max")


def test_migration_writes_both_versions_and_reads_one(client):
    old, new = repo(client, 1), repo(client, 2)
    mirrored = MirroredVectorRepository(read=old, writes=[old, new])
    store(mirrored)
    assert old.count() == new.count() == 2
    assert {h.metadata["source_id"] for h in mirrored.search([1.0, 0.0], top_k=1, query_text=QUESTION)} == {"install"}
    mirrored.delete_by_filter({"metadata.source_id": "install"})
    assert old.count() == new.count() == 1
    with pytest.raises(ValueError):
        MirroredVectorRepository(read=old, writes=[new])


def test_the_query_instruction_goes_on_queries_only():
    port = MagicMock(embedding_dim=2, is_remote=True)
    port.encode_single.return_value = np.zeros(2)
    port.encode_texts.return_value = [np.zeros(2)]
    gen = DefaultEmbeddingGenerator(port=port, query_prefix="Instruct: find passages\nQuery: ")
    gen.generate_query_embedding("what is a namespace")
    port.encode_single.assert_called_once_with("Instruct: find passages\nQuery: what is a namespace")
    gen.generate_embeddings([{"text": "A project is a namespace."}])
    port.encode_texts.assert_called_once_with(["A project is a namespace."])


def test_a_source_at_an_older_index_version_re_ingests_every_page():
    from core.data_sources.types.web.pipeline_handler import WebPipelineHandler

    url = "https://docs.example.com/en/doc"
    page = SimpleNamespace(url=url, html="<p>x</p>", content_hash="h", etag="e", last_modified="")
    for stored_version, expect_changed in ((1, True), (2, False)):
        connector = MagicMock()
        connector.iter_pages.return_value = iter([(url, page)])
        sources = MagicMock()
        sources.get_by_id.return_value = SimpleNamespace(type_data={
            "urls": [url], "pages": {url: {"content_hash": "h", "title": "t"}}, "index_version": stored_version})
        handler = WebPipelineHandler(lambda: connector, MagicMock(), MagicMock(), sources, index_version=2)
        changed = handler.collect(SimpleNamespace(source_id="s", source_name="n"))
        assert (len(changed) == 1) is expect_changed, f"stored index version {stored_version}"
        previous_passed = connector.iter_pages.call_args.args[1]
        assert (previous_passed == {}) is expect_changed, "a re-ingestion fetches unconditionally"
        assert handler.get_summary(None, None)["index_version"] == 2
