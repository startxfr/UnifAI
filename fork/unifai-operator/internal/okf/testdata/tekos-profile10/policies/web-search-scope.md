---
okf_version: "0.2"
type: policy
title: Web search fallback scope
resource: https://github.com/startxfr/zuno-demo-agents/blob/main/agents/tekos/policies/web-search-scope.md
stale_after: "2027-05-15T00:00:00Z"
zuno:
  profile: "1.0"
  narrows_platform_policy: true
  constraint_type: data_handling_addendum
  applies_to:
    tasks:
      - answer-technical-question
    tools:
      - web_search
  rationale: >-
    web_search is answer-technical-question's fallback when the indexed
    knowledge.tech/knowledge.project corpus and search_confluence's live
    read do not ground an answer. Unlike those two paths, its results carry
    no classification or ACL metadata, and the query text itself leaves the
    platform for an external search provider. This agent therefore
    restricts web_search queries to public technical topics: no customer
    name, project_id or other content derived from the knowledge.project
    domain may appear in a web_search query, even though the task's C1
    classification would otherwise permit the call. This is strictly
    narrower than what policies/tools/tool-policy.yaml permits for
    web_search; it grants nothing.
  enforcement:
    mechanism: none-yet
    notes: >-
      Stated as an instruction in prompts/answer-technical-question.md;
      no code checks the query. A request-content filter on the web_search
      call would enforce it. Recorded as a known gap rather than a false
      claim of enforcement (zuno-demo ADR-0513).
---

# Web search fallback scope

Additional, agent-specific constraint on Tekos's `web_search` fallback: a
query carries public technical terms only, never customer or project data.
It narrows only; `policies/tools/tool-policy.yaml`'s `web_search` entry is
the platform floor it sits inside.
