---
okf_version: "0.2"
type: rag
title: Technical documentation retrieval
resource: https://github.com/startxfr/zuno-demo-agents/blob/main/agents/tekos/rag/tech.md
stale_after: "2027-05-15T00:00:00Z"
zuno:
  profile: "1.0"
  domain: knowledge.tech
  used_by_tasks:
    - answer-technical-question
    - find-relevant-docs
  freshness_expectation: semantic-read
  rationale: >-
    Tekos's core value is grounded technical Q&A. answer-technical-question
    retrieves from knowledge.tech first and uses search_confluence, then
    web_search, only when the retrieved documents do not ground an answer.
    find-relevant-docs uses it to list the documentation sections on a
    topic. Both tasks use the agent-wide zuno.rag.top_k (5); no per-domain
    override is needed.
---

# Technical documentation retrieval

Tekos's primary knowledge domain (zuno-demo ADR-0202): official Red Hat
product documentation (C1) and internal Confluence content (C2). Access is
the tasks' `allowed_knowledge` intersected with
`policies/knowledge/knowledge-policy.yaml` (groups consultant, board, cdp);
this note grants nothing.

Known gap: the corpus covers Red Hat products, and the domain's technology
vocabulary is satellite, openshift, openshift-ai and keycloak. It held no Go
language documentation when last checked (2026-09), so a Go question is not
grounded in it.
