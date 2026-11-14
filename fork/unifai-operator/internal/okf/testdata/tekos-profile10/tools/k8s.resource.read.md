---
okf_version: "0.2"
type: tool
title: Kubernetes resource read
resource: https://github.com/startxfr/zuno-demo-agents/blob/main/agents/tekos/tools/k8s.resource.read.md
stale_after: "2027-05-15T00:00:00Z"
zuno:
  profile: "1.0"
  capability: k8s.resource.read
  used_by_tasks:
    - answer-technical-question
  usage_notes: >-
    Takes an apiVersion, a kind, a name and a namespace; returns that one
    resource. answer-technical-question uses it for operations questions
    such as "why does this pod not start?", after k8s.resource.list has
    found the resource.
  known_limitations:
    - "zuno-* namespaces only. Secret and ConfigMap are never returned."
    - "Data classification C2 (min_classification); no external_model_policy restriction."
    - "Allowed groups: ocp-ai-ops only. The business personas get no cluster reads through Tekos."
    - "Access: read."
---

# Kubernetes resource read

One of Tekos's read-only cluster reads (zuno-demo ADR-0600), for the
operations persona.

This note grants nothing: the task's `allowed_tools` and
`policies/tools/tool-policy.yaml` decide.
