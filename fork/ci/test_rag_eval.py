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
