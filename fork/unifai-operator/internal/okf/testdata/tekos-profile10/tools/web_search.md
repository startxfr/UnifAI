---
okf_version: "0.2"
type: tool
title: Constrained web search
resource: https://github.com/startxfr/zuno-demo-agents/blob/main/agents/tekos/tools/web_search.md
stale_after: "2027-05-15T00:00:00Z"
zuno:
  profile: "1.0"
  capability: web_search
  used_by_tasks:
    - answer-technical-question
  usage_notes: >-
    Takes a search query and returns web results. answer-technical-question
    calls it last, only when neither the retrieved documents
    (knowledge.tech, knowledge.project) nor search_confluence ground an
    answer; the answer still cites its sources. The query stays on public
    technical topics (policies/web-search-scope.md of this bundle).
  known_limitations:
    - "Data classification C1 (min_classification); no external_model_policy restriction, so its results may reach external models."
    - "Allowed groups: sales, consultant, adv, finance, board."
    - "Access: read."
    - "Results carry no classification or ACL metadata, and the query text leaves the platform for an external search provider."
    - "Where no search provider is configured, the tool returns no results; the task then answers from the documents already retrieved."
---

# Constrained web search

The last-resort source of `answer-technical-question`, after the indexed
documentation, project memory and the live Confluence read. This bundle
narrows it further in `policies/web-search-scope.md`: no customer name,
`project_id` or project-memory content in a query.

This note grants nothing: the task's `allowed_tools` and
`policies/tools/tool-policy.yaml` decide.
