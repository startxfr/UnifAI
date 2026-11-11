"""docs_rag retriever: forward_user_token sends the user's own token to the RAG service."""
from unittest.mock import MagicMock

from mas.core.element_deps import ElementBuildContext
from mas.core.execution_context import ExecutionContext, ExecutionContextHolder
from mas.core.identity import resolve_identity
from mas.core.identity_forwarding import IdentityTokenSource
from mas.elements.retrievers.docs_rag.config import DocsRagRetrieverConfig
from mas.elements.retrievers.docs_rag.docs_rag_retriever_factory import DocsRagRetrieverFactory


class Source(IdentityTokenSource):
    def bind(self, session_id, identity_session_id, username):
        pass

    def get_access_token(self, session_id, username):
        return f"tok-{username}"


def _deps():
    holder = ExecutionContextHolder()
    holder.context = ExecutionContext(session_id="s1", identity=resolve_identity("alice", "user"))
    return ElementBuildContext(execution_ctx=holder, identity_token_source=Source())


def _retriever(forward):
    r = DocsRagRetrieverFactory().create(DocsRagRetrieverConfig(forward_user_token=forward), deps=_deps())
    r._provider = MagicMock()
    r._provider.query.return_value = MagicMock(matches=[])
    return r


def test_forwarding_adds_the_users_bearer_token():
    r = _retriever(True)
    r.retrieve("q")
    kwargs = r._provider.query.call_args.kwargs
    assert kwargs["extra_headers"] == {"Authorization": "Bearer tok-alice"}
    assert kwargs["authenticated_user"] == "alice"


def test_default_sends_no_token():
    r = _retriever(False)
    r.retrieve("q")
    assert r._provider.query.call_args.kwargs["extra_headers"] is None


def test_source_type_selects_the_generic_endpoint():
    from unittest.mock import MagicMock as M
    from mas.elements.providers.rag_client.client import RagClient
    c = RagClient(base_url="http://rag", authenticated_user="alice")
    c._client = M()
    c._client.get.return_value = M(json=lambda: {"matches": []}, raise_for_status=lambda: None)
    c.query_match("q", source_type="confluence")
    url, params = c._client.get.call_args.args[0], c._client.get.call_args.kwargs["params"]
    assert url.endswith("/api/sources/query.match") and params["sourceType"] == "CONFLUENCE"
    c.query_match("q")
    assert c._client.get.call_args.args[0].endswith("/api/docs/query.match")


def test_retriever_passes_its_source_type():
    r = DocsRagRetrieverFactory().create(DocsRagRetrieverConfig(source_type="CONFLUENCE"), deps=_deps())
    r._provider = MagicMock()
    r._provider.query.return_value = MagicMock(matches=[])
    r.retrieve("q")
    assert r._provider.query.call_args.kwargs["source_type"] == "CONFLUENCE"


def _match(score, text):
    m = MagicMock(score=score)
    m.model_dump.return_value = {"score": score, "text": text}
    return m


def test_extra_source_types_are_queried_and_merged_by_score():
    cfg = DocsRagRetrieverConfig(source_type="CONFLUENCE", extra_source_types=["WEB"], top_k_results=3, threshold=0.3)
    r = DocsRagRetrieverFactory().create(cfg, deps=_deps())
    r._provider = MagicMock()
    by_type = {
        "CONFLUENCE": [_match(0.9, "c1"), _match(0.5, "c2"), _match(0.1, "low")],
        "WEB": [_match(0.8, "w1"), _match(0.4, "w2")],
    }
    r._provider.query.side_effect = lambda **kw: MagicMock(matches=by_type[kw["source_type"]])
    out = r.retrieve("q")
    assert [m["text"] for m in out] == ["c1", "w1", "c2"]
    assert [c.kwargs["source_type"] for c in r._provider.query.call_args_list] == ["CONFLUENCE", "WEB"]


def test_without_extra_source_types_one_query_in_provider_order():
    r = DocsRagRetrieverFactory().create(DocsRagRetrieverConfig(source_type="CONFLUENCE"), deps=_deps())
    r._provider = MagicMock()
    r._provider.query.return_value = MagicMock(matches=[_match(0.4, "a"), _match(0.9, "b")])
    out = r.retrieve("q")
    assert [m["text"] for m in out] == ["a", "b"]
    assert r._provider.query.call_count == 1


def test_rrf_merges_by_rank_so_one_source_type_cannot_outrank_the_other_by_scale():
    cfg = DocsRagRetrieverConfig(source_type="WEB", extra_source_types=["GIT"], top_k_results=4, threshold=0.0,
                                 source_merge="rrf")
    r = DocsRagRetrieverFactory().create(cfg, deps=_deps())
    r._provider = MagicMock()
    by_type = {
        "WEB": [_match(1.4, "w1"), _match(1.3, "w2"), _match(1.2, "w3")],
        "GIT": [_match(2.8, "g1"), _match(2.7, "g2"), _match(2.6, "g3")],
    }
    r._provider.query.side_effect = lambda **kw: MagicMock(matches=by_type[kw["source_type"]])
    assert [m["text"] for m in r.retrieve("q")] == ["w1", "g1", "w2", "g2"]
    score = DocsRagRetrieverFactory().create(
        DocsRagRetrieverConfig(source_type="WEB", extra_source_types=["GIT"], top_k_results=4, threshold=0.0), deps=_deps())
    score._provider = r._provider
    assert [m["text"] for m in score.retrieve("q")] == ["g1", "g2", "g3", "w1"]


def test_rrf_keeps_the_threshold_and_a_single_type_unchanged():
    r = DocsRagRetrieverFactory().create(
        DocsRagRetrieverConfig(source_type="WEB", extra_source_types=["GIT"], top_k_results=3, threshold=0.5,
                               source_merge="rrf"), deps=_deps())
    r._provider = MagicMock()
    by_type = {"WEB": [_match(0.9, "w1"), _match(0.2, "low")], "GIT": []}
    r._provider.query.side_effect = lambda **kw: MagicMock(matches=by_type[kw["source_type"]])
    assert [m["text"] for m in r.retrieve("q")] == ["w1"]
    single = DocsRagRetrieverFactory().create(
        DocsRagRetrieverConfig(source_type="WEB", source_merge="rrf"), deps=_deps())
    single._provider = MagicMock()
    single._provider.query.return_value = MagicMock(matches=[_match(0.4, "a"), _match(0.9, "b")])
    assert [m["text"] for m in single.retrieve("q")] == ["a", "b"]
