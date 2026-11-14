---
okf_version: "0.2"
type: tool
title: Confluence page search
resource: https://github.com/startxfr/zuno-demo-agents/blob/main/agents/tekos/tools/search_confluence.md
stale_after: "2027-05-15T00:00:00Z"
zuno:
  profile: "1.0"
  capability: search_confluence
  used_by_tasks:
    - answer-technical-question
    - find-relevant-docs
  live_read: true
  usage_notes: >-
    Takes a text query and returns the matching pages of the internal
    Confluence spaces. In answer-technical-question it is the
    live_read_tool: the turn calls it when the indexed knowledge.tech corpus
    alone does not ground an answer, so the answer can use content newer
    than the last ingestion. In find-relevant-docs it finds the Confluence
    pages on the requested topic, returned as a list rather than an answer.
  known_limitations:
    - "Data classification C2 (min_classification). Its results must stay on local models (external_model_policy.allow_context: false), even though Tekos's ceiling is C1."
    - "Allowed groups: consultant, board, cdp, lightspeed_readonly, ocp-ai-ops."
    - "Access: read. It changes nothing in Confluence."
---

# Confluence page search

Searches the internal Confluence spaces. `search_confluence` is the legacy
name of the canonical capability `confluence.page.search`. It is the live
complement of the Confluence content indexed in `knowledge.tech`.

This note grants nothing: each task's `allowed_tools` and
`policies/tools/tool-policy.yaml` decide.
