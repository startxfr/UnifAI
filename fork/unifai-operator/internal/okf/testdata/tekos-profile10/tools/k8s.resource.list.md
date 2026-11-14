---
okf_version: "0.2"
type: tool
title: Kubernetes resource list
resource: https://github.com/startxfr/zuno-demo-agents/blob/main/agents/tekos/tools/k8s.resource.list.md
stale_after: "2027-05-15T00:00:00Z"
zuno:
  profile: "1.0"
  capability: k8s.resource.list
  used_by_tasks:
    - answer-technical-question
  usage_notes: >-
    Takes an apiVersion, a kind and a namespace; returns the resources of
    that kind in the namespace, for example its Pods or Deployments.
    answer-technical-question uses it to find the resource an operations
    question is about.
  known_limitations:
    - "zuno-* namespaces only. Secret and ConfigMap are never returned."
    - "Data classification C2 (min_classification); no external_model_policy restriction."
    - "Allowed groups: ocp-ai-ops only. The business personas get no cluster reads through Tekos."
    - "Access: read."
---

# Kubernetes resource list

One of Tekos's read-only cluster reads (zuno-demo ADR-0600), for the
operations persona.

This note grants nothing: the task's `allowed_tools` and
`policies/tools/tool-policy.yaml` decide.
