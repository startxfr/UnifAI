---
okf_version: "0.2"
type: tool
title: Kubernetes events read
resource: https://github.com/startxfr/zuno-demo-agents/blob/main/agents/tekos/tools/k8s.events.read.md
stale_after: "2027-05-15T00:00:00Z"
zuno:
  profile: "1.0"
  capability: k8s.events.read
  used_by_tasks:
    - answer-technical-question
  usage_notes: >-
    Takes a namespace; returns its Kubernetes events.
    answer-technical-question uses it to explain why a pod does not start
    or keeps restarting.
  known_limitations:
    - "zuno-* namespaces only."
    - "Data classification C2 (min_classification); no external_model_policy restriction."
    - "Allowed groups: ocp-ai-ops only. The business personas get no cluster reads through Tekos."
    - "Access: read."
---

# Kubernetes events read

One of Tekos's read-only cluster reads (zuno-demo ADR-0600), for the
operations persona.

This note grants nothing: the task's `allowed_tools` and
`policies/tools/tool-policy.yaml` decide.
