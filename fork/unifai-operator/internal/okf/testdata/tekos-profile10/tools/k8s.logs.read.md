---
okf_version: "0.2"
type: tool
title: Kubernetes logs read
resource: https://github.com/startxfr/zuno-demo-agents/blob/main/agents/tekos/tools/k8s.logs.read.md
stale_after: "2027-05-15T00:00:00Z"
zuno:
  profile: "1.0"
  capability: k8s.logs.read
  used_by_tasks:
    - answer-technical-question
  usage_notes: >-
    Takes a pod and its namespace; returns the pod's logs.
    answer-technical-question uses it when the events and the resource
    alone do not explain a failure.
  known_limitations:
    - "zuno-* namespaces only."
    - "Application logs may contain sensitive values: the result is treated as C2 (min_classification); no external_model_policy restriction."
    - "Allowed groups: ocp-ai-ops only. The business personas get no cluster reads through Tekos."
    - "Access: read."
---

# Kubernetes logs read

One of Tekos's read-only cluster reads (zuno-demo ADR-0600), for the
operations persona.

This note grants nothing: the task's `allowed_tools` and
`policies/tools/tool-policy.yaml` decide.
