---
okf_version: "0.2"
type: tool
title: Metrics query
resource: https://github.com/startxfr/zuno-demo-agents/blob/main/agents/tekos/tools/metrics.query.md
stale_after: "2027-05-15T00:00:00Z"
zuno:
  profile: "1.0"
  capability: metrics.query
  used_by_tasks:
    - answer-technical-question
  usage_notes: >-
    Takes one instant PromQL query, which must carry a label matcher (for
    example kube_pod_status_phase{namespace="zuno-ai-run"}); returns its
    result from the cluster monitoring. answer-technical-question uses it
    for operations questions about the current state of a workload.
  known_limitations:
    - "One instant query per call, with a label matcher."
    - "The query is scoped to the namespaces the caller is entitled to (zuno-demo ADR-0603): a series without a namespace label, such as a node metric, returns nothing."
    - "Data classification C2 (min_classification); no external_model_policy restriction."
    - "Allowed groups: ocp-ai-ops only. The business personas get no cluster reads through Tekos."
    - "Access: read."
---

# Metrics query

One of Tekos's read-only cluster reads (zuno-demo ADR-0600), for the
operations persona.

This note grants nothing: the task's `allowed_tools` and
`policies/tools/tool-policy.yaml` decide.
