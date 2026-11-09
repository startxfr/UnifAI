#!/usr/bin/env python3
"""Retriever ranking evaluation over a live UnifAI RAG server (query.bearer).

    RAG_TOKEN=<a user's bearer token> python3 fork/ci/rag_eval.py --url https://<rag route> \
        --set ranking.yaml [--top-k 10] [--json out.json]

The set is zuno-demo's evaluations/redhat-docs/ranking.yaml: entries {id, query, sourceType, tags, expect (URL
fragments), expect_none}. A hit is a result whose source URL contains one of the fragments, after folding the
docs.redhat.com /documentation/ and /en/documentation/ forms. Reports hit@1, hit@5, MRR over the entries that
expect something, and the top score of the entries that expect nothing (to set a relevance threshold).
The token is read from RAG_TOKEN and never printed. Queries are read-only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request

import yaml


def fold(url: str) -> str:
    """docs.redhat.com serves a book under /documentation/ and /en/documentation/: compare one form."""
    return re.sub(r"/en/documentation/", "/documentation/", url or "").rstrip("/")


def result_url(hit: dict) -> str:
    md = hit.get("metadata") or {}
    return md.get("url") or md.get("source_url") or md.get("page_url") or ""


def first_hit(results: list[dict], expect: list[str]) -> int | None:
    """1-based rank of the first result matching an expected fragment, or None."""
    wanted = [fold(e) for e in expect]
    for rank, hit in enumerate(results, 1):
        url = fold(result_url(hit))
        if any(w in url for w in wanted):
            return rank
    return None


def query(base: str, token: str, entry: dict, top_k: int) -> list[dict]:
    params = {"query": entry["query"], "sourceType": entry.get("sourceType", "WEB"), "top_k_results": top_k}
    tags = entry.get("tags") or []
    if tags:  # a repeated parameter: tags=a&tags=b
        params["tags"] = [tags] if isinstance(tags, str) else list(tags)
    req = urllib.request.Request(f"{base.rstrip('/')}/api/sources/query.bearer?{urllib.parse.urlencode(params, doseq=True)}",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 (operator-given URL)
        body = json.load(resp)
    return body.get("matches") or body.get("results") or []


def evaluate(entries: list[dict], run) -> dict:
    rows, ranks, none_scores = [], [], []
    for e in entries:
        results = run(e)
        top = results[0]["score"] if results else None
        if e.get("expect_none"):
            none_scores.append(top or 0.0)
            rows.append({"id": e["id"], "expect_none": True, "top_score": top})
            continue
        rank = first_hit(results, e.get("expect") or [])
        ranks.append(rank)
        rows.append({"id": e["id"], "rank": rank, "top_score": top, "top_url": result_url(results[0]) if results else ""})
    n = len(ranks) or 1
    return {
        "hit@1": sum(1 for r in ranks if r == 1) / n,
        "hit@5": sum(1 for r in ranks if r and r <= 5) / n,
        "mrr": sum(1 / r for r in ranks if r) / n,
        "missed": [row["id"] for row in rows if not row.get("expect_none") and row["rank"] is None],
        "expect_none_top_scores": none_scores,
        "threshold_gap": threshold_gap(rows),
        "rows": rows,
    }


def threshold_gap(rows: list[dict]) -> float | None:
    """Lowest top score of an answered question minus the highest top score of an out-of-corpus one. Above 0 a
    relevance threshold separates the two (R-518: the mmarco reranker had none); None without both kinds."""
    answered = [r["top_score"] for r in rows if not r.get("expect_none") and r.get("rank") and r.get("top_score") is not None]
    none = [r["top_score"] for r in rows if r.get("expect_none") and r.get("top_score") is not None]
    if not answered or not none:
        return None
    return min(answered) - max(none)


def compare(a: dict, b: dict) -> dict:
    """A/B of two reports (--json files): metric deltas (b minus a) and the questions whose rank changed."""
    ra = {r["id"]: r.get("rank") for r in a["rows"] if not r.get("expect_none")}
    rb = {r["id"]: r.get("rank") for r in b["rows"] if not r.get("expect_none")}
    changed = [{"id": i, "from": ra[i], "to": rb[i]} for i in ra if i in rb and ra[i] != rb[i]]
    return {
        "delta": {k: (b[k] - a[k]) for k in ("hit@1", "hit@5", "mrr")},
        "threshold_gap": {"a": a.get("threshold_gap"), "b": b.get("threshold_gap")},
        "changed": changed,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", help="RAG server base URL")
    ap.add_argument("--set", help="evaluation YAML")
    ap.add_argument("--compare", nargs=2, metavar=("A.json", "B.json"), help="diff two --json reports and stop")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--json", help="write the full report here")
    args = ap.parse_args(argv)
    if args.compare:
        with open(args.compare[0], encoding="utf-8") as fa, open(args.compare[1], encoding="utf-8") as fb:
            print(json.dumps(compare(json.load(fa), json.load(fb)), indent=2))
        return 0
    if not args.url or not args.set:
        ap.error("--url and --set are required unless --compare is used")
    token = os.environ.get("RAG_TOKEN", "")
    if not token:
        print("RAG_TOKEN is not set", file=sys.stderr)
        return 2
    with open(args.set, encoding="utf-8") as fh:
        entries = yaml.safe_load(fh)
    report = evaluate(entries, lambda e: query(args.url, token, e, args.top_k))
    print(f"hit@1 {report['hit@1']:.2f}  hit@5 {report['hit@5']:.2f}  MRR {report['mrr']:.2f}  "
          f"threshold_gap {report['threshold_gap']}  missed {report['missed']}  expect_none top scores {report['expect_none_top_scores']}")
    for row in report["rows"]:
        print(json.dumps(row))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
