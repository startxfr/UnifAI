"""fork/ci/rag_eval.py: matching and metrics, without a server."""
import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location("rag_eval", pathlib.Path(__file__).with_name("rag_eval.py"))
rag_eval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rag_eval)

AUTH = "openshift_container_platform/4.22/html-single/authentication_and_authorization"


def hit(url, score=0.9):
    return {"score": score, "metadata": {"url": url}}


def test_en_and_plain_documentation_forms_match():
    results = [hit("https://docs.redhat.com/en/documentation/" + AUTH + "/index")]
    assert rag_eval.first_hit(results, [AUTH]) == 1
    assert rag_eval.first_hit([hit("https://docs.redhat.com/documentation/" + AUTH)], [AUTH]) == 1


def test_metrics():
    entries = [{"id": 1, "query": "q1", "expect": [AUTH]}, {"id": 2, "query": "q2", "expect": ["storage"]},
               {"id": 3, "query": "q3", "expect": ["registry"]}, {"id": 4, "query": "q4", "expect_none": True}]
    answers = {
        "q1": [hit("https://x/en/documentation/" + AUTH)],
        "q2": [hit("https://x/install"), hit("https://x/storage")],
        "q3": [hit("https://x/install")],
        "q4": [hit("https://x/other", 0.2)],
    }
    r = rag_eval.evaluate(entries, lambda e: answers[e["query"]])
    assert r["hit@1"] == 1 / 3 and r["hit@5"] == 2 / 3
    assert abs(r["mrr"] - (1 + 0.5) / 3) < 1e-9
    assert r["missed"] == [3] and r["expect_none_top_scores"] == [0.2]


def test_tags_are_sent_as_repeated_parameters(monkeypatch):
    seen = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"matches": []}'

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        return Resp()

    monkeypatch.setattr(rag_eval.urllib.request, "urlopen", fake_urlopen)
    rag_eval.query("http://rag:13456/", "tok", {"query": "q", "sourceType": "WEB", "tags": ["a", "b"]}, 7)
    assert "tags=a&tags=b" in seen["url"] and "top_k_results=7" in seen["url"] and "sourceType=WEB" in seen["url"]
    rag_eval.query("http://rag:13456", "tok", {"query": "q", "tags": "knowledge.tech"}, 3)
    assert "tags=knowledge.tech" in seen["url"]


def test_threshold_gap_and_compare():
    entries = [{"id": 1, "query": "q1", "expect": ["a"]}, {"id": 2, "query": "q2", "expect": ["b"]},
               {"id": 3, "query": "q3", "expect_none": True}]
    first = {"q1": [hit("https://x/a", 0.9)], "q2": [hit("https://x/z", 0.8), hit("https://x/b", 0.7)], "q3": [hit("https://x/o", 0.95)]}
    second = {"q1": [hit("https://x/a", 0.9)], "q2": [hit("https://x/b", 0.8)], "q3": [hit("https://x/o", 0.3)]}
    a = rag_eval.evaluate(entries, lambda e: first[e["query"]])
    b = rag_eval.evaluate(entries, lambda e: second[e["query"]])
    assert abs(a["threshold_gap"] - (0.7 - 0.95)) < 1e-9 or abs(a["threshold_gap"] - (0.8 - 0.95)) < 1e-9
    assert a["threshold_gap"] < 0 < b["threshold_gap"]
    c = rag_eval.compare(a, b)
    assert c["changed"] == [{"id": 2, "from": 2, "to": 1}]
    assert c["delta"]["hit@1"] == 0.5


def test_merged_types_sort_by_score_and_match_git_fragments():
    entry = {"id": 1, "query": "q", "sourceType": "WEB", "expect": ["web-page"], "expect_git": ["modules/log-forwarding"]}
    answers = {"WEB": [hit("https://x/other", 0.5)], "GIT": [hit("https://github.com/o/r/blob/main/modules/log-forwarding.adoc", 0.8)]}
    run = rag_eval.merged_run(["WEB", "GIT"], 0.3, lambda e, k: answers[e["sourceType"]])
    res = run(entry, 10)
    assert [h["_type"] for h in res] == ["GIT", "WEB"]
    assert rag_eval.first_hit_merged(res, entry) == 1
    # below the threshold the git page is dropped, and a web hit still uses `expect`
    res = rag_eval.merged_run(["WEB", "GIT"], 0.9, lambda e, k: answers[e["sourceType"]])(entry, 10)
    assert res == [] and rag_eval.first_hit_merged(res, entry) is None
    web_entry = dict(entry, expect=["other"], expect_git=[])
    assert rag_eval.first_hit_merged(run(web_entry, 10), web_entry) == 2


def test_merge_leaves_other_source_types_alone():
    calls = []

    def one(e, k):
        calls.append(e["sourceType"])
        return [hit("https://x/" + e["sourceType"], 0.7)]

    run = rag_eval.merged_run(["WEB", "GIT"], 0.0, one)
    res = run({"id": 1, "query": "q", "sourceType": "CONFLUENCE", "expect": ["CONFLUENCE"]}, 10)
    assert calls == ["CONFLUENCE"] and "_type" not in res[0]
    assert rag_eval.first_hit_merged(res, {"sourceType": "CONFLUENCE", "expect": ["CONFLUENCE"]}) == 1


def test_rows_carry_best_score_per_type_when_merged():
    results = [{"score": 2.4, "_type": "GIT", "source": {"url": "https://github.com/o/r/blob/x/a.adoc"}},
               {"score": 1.5, "_type": "WEB", "source": {"url": "https://example.com/a"}},
               {"score": 1.1, "_type": "GIT", "source": {"url": "https://github.com/o/r/blob/x/b.adoc"}}]
    report = rag_eval.evaluate([{"id": 1, "query": "q", "expect": ["example.com/a"]}], lambda e: results)
    assert report["rows"][0]["by_type"] == {"GIT": 2.4, "WEB": 1.5}
    plain = rag_eval.evaluate([{"id": 1, "query": "q", "expect": ["a"]}], lambda e: [{"score": 1.0, "url": "a"}])
    assert "by_type" not in plain["rows"][0]


def test_fusions_merge_ranked_lists_without_comparing_scales():
    web = [{"score": 1.4, "id": "w1"}, {"score": 1.3, "id": "w2"}, {"score": 1.2, "id": "w3"}]
    git = [{"score": 2.8, "id": "g1"}, {"score": 2.7, "id": "g2"}, {"score": 2.6, "id": "g3"}]
    ids = lambda r: [h["id"] for h in r]
    assert ids(rag_eval.fuse([web, git], "score", 4)) == ["g1", "g2", "g3", "w1"]
    assert ids(rag_eval.fuse([web, git], "interleave", 4)) == ["w1", "g1", "w2", "g2"]
    assert set(ids(rag_eval.fuse([web, git], "rrf", 2))) == {"w1", "g1"}
    assert ids(rag_eval.fuse([web, []], "rrf", 5)) == ["w1", "w2", "w3"]
    try:
        rag_eval.fuse([web], "nope", 1)
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown fusion must be refused")
