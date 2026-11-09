# Reranker evaluation protocol (R-518)

Prepared 2026-11-09, **not run**: it needs a GPU window and a cluster action (owner of the GPU: zuno-demo). Nothing here touches
the live stack.

## Why it was closed, and what would reopen it
CPU reranking failed on cost and quality (ROADMAP R-518): bge-reranker-base needed ~0.9 s per candidate (30 candidates = 27 s, client
timeout 10 s); ms-marco-MiniLM-L-6-v2 is English-only and ranked worse than DBSF alone on French questions; mmarco-mMiniLMv2-L12
left no relevance threshold (an out-of-corpus question scored like an answered one). The operator keeps `spec.rag.reranker`
(`mode: remote` takes a `url`), so a GPU-served model needs no operator release.

## Candidate
- `BAAI/bge-reranker-v2-m3`: multilingual (French and English), XLM-RoBERTa large, served by Text Embeddings Inference on a GPU.
  Before the window, check that the TEI image we would use lists this architecture; if not, the run stops there.
- Others only if the first one fails and TEI support is confirmed.

## Baseline (do not re-measure before the run, take the same day's numbers)
EN21 hit@1 / hit@5 / MRR 0.71 / 0.86 / 0.77 (DBSF, no reranker, complete web corpus: the 0.62 / 0.76 / 0.69 of 2026-11-09 comes from
the truncated crawl, see R-530); FR10 0.80 / 0.90 / 0.83; all 34: 0.68 / 0.81 / 0.74. Set: zuno-demo `evaluations/redhat-docs/ranking.yaml`.
The baseline and the candidate must read the same sources (same `sourceType`, same corpus): if R-530 changes the corpus between
the two runs, redo the baseline.

## Run (the user's go, one GPU window)
1. Deploy TEI with the model on a GPU node, in the stack namespace, as a separate Deployment/Service (not the operator's CPU `deploy` mode).
2. `spec.rag.reranker: {mode: remote, url: http://<svc>:80, candidates: 30}` and `spec.extraEnv.rag` `RERANKER_TIMEOUT_SECONDS` if the
   default 10 s is tight. One rag roll.
3. Measure with the same persona, top_k 10:
   `RAG_TOKEN=... python3 fork/ci/rag_eval.py --url <rag route> --set ranking.yaml --top-k 10 --json after.json`
4. Compare to the baseline file: `python3 fork/ci/rag_eval.py --compare before.json after.json` (metric deltas, questions whose rank
   changed, and `threshold_gap`).
5. Measure the latency per query (the run's wall time over 34 queries) and the GPU memory of the TEI pod.
6. Put the reranker back to unset (or keep it if accepted) and write the result in R-518.

## Acceptance (all required)
- EN21 hit@1 at least +0.05 over the baseline, no drop on FR10 hit@1 (0.80), MRR never below baseline on any group.
- `threshold_gap` above 0: a relevance threshold exists between the answered and the out-of-corpus questions (this is the gap that
  made the earlier model unusable for `docs_rag`).
- p95 search latency under 3 s with 30 candidates.
Otherwise R-518 stays closed with the numbers recorded.
