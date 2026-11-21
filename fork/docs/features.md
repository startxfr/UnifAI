# Features of the fork

What the fork adds to upstream UnifAI, in one line each. The backlog row (R-xxx) in [Roadmap](roadmap.md) is authoritative for status, dates, commits and proofs; this page is only a map. Rows delivered and closed are in [the archive](roadmap-archive.md).

| Area | Feature | Row |
|---|---|---|
| Agents | Read-only A2A delegation of a bundle through the zuno a2a-gateway (`spec.delegation`, `spec.ceilings.delegationTargets`) | R-513 |
| Agents | Orchestrator system message: mark the work item done first, no re-delegation for an offer of detail | R-559 |
| Agents | A2A streaming no longer prefixes answers with "Task status: ..." | R-558 |
| Agents | Token ceiling of one user turn (`zuno.limits.max_tokens_per_turn`, `spec.ceilings.maxTokensPerTurn`) | R-543 |
| Agents | Delegation spans carry `mas.delegation.work_item_id` and `mas.delegation.target` | R-560 |
| Agents | A work item is delegated at most twice by default (`MAS_MAX_DELEGATIONS_PER_ITEM`, 0 = unlimited; set with `spec.extraEnv`) | R-563 |
| Agents | A `retrieve_first` failure is visible: event `retrieve_first.failed` (attribute `mas.retrieve_first.error`, the exception class only) and counter `mas.retrieve_first.failures`; the turn still runs without context | R-564 |
| RAG | Retriever ranking: DBSF fusion, BM25 v2 index, reranker option (`spec.rag.search`, `spec.rag.reranker`); evaluation in [Reranker evaluation](reranker-eval.md) | R-514, R-518 |
| RAG | French sparse encoder v3, opt-in and off by default | R-522 |
| RAG | Git sources (`type: git`), see [RAG git sources](rag-git-sources.md) | R-530 |
| Operator | `OUTBOUND_ALLOWED_HOSTS` set by the operator on multiagent and the temporal worker | R-544 |
| Operator | Neutral contract namespace (`contractNamespace`), `redhat-docs` crawl mode removed | R-556 |
| Operator | OKF profile 1.0 bundles, legacy `v0.2`/`v0.3` still read on the 0.1 line | R-557 |
| Delivery | One product version, signed images, weekly releases, promotion: [Releasing](releasing.md), [CI and testing](ci-and-testing.md) | R-526 |
