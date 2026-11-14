---
okf_version: "0.2"
type: rag
title: Project memory retrieval
resource: https://github.com/startxfr/zuno-demo-agents/blob/main/agents/tekos/rag/project.md
stale_after: "2027-05-15T00:00:00Z"
zuno:
  profile: "1.0"
  domain: knowledge.project
  used_by_tasks:
    - answer-technical-question
  freshness_expectation: semantic-read
  rationale: >-
    answer-technical-question also retrieves knowledge.project (zuno-demo
    ADR-0209), so a consultant's answer can draw on the durable,
    cross-session memory of their current engagement (project_id), not
    just the documentation corpus. The domain is written when a session's
    memory is extracted, not ingested on a schedule, so no staleness or
    top_k override applies.
---

# Project memory retrieval

Cross-session, cross-agent project memory, scoped by `project_id` and
extracted from conversations rather than ingested from a source system.
`policies/knowledge/knowledge-policy.yaml` lists every business group for
this domain: membership of the project decides access. This note grants
nothing.

This bundle's `policies/web-search-scope.md` forbids putting content from
this domain in a `web_search` query.
