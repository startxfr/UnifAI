---
okf_version: "0.2"
type: task
title: Write code
description: Write code, configuration or a script directly in the reply, without tools or retrieval.
resource: https://github.com/startxfr/zuno-demo-agents/blob/main/agents/tekos/tasks/write-code.md
stale_after: "2027-05-15T00:00:00Z"
zuno:
  profile: "1.0"
  allowed_tools: []
  allowed_knowledge: []
  # The model roles this task prefers, in order, matching its entry in
  # policies/model-routing/model-routing-policy.yaml (a code-specialized
  # model first, local models as fallbacks); the routing policy stays the
  # authority.
  models:
    preferred:
      - code
      - specialized
      - reasoning
      - quality
  # Example prompts a user interface can offer for this task. Display only: choosing one does not select the task.
  prompt_examples:
    - "Write an Ansible task that waits for a Deployment to finish rolling out."
    - "Generate a Kubernetes NetworkPolicy allowing ingress only from the istio-system namespace."
    - "Write a Go function that verifies an RS256 JWT against a JWKS endpoint."
---

# Write code

Generate code, configuration or a script (Terraform, Ansible, Kubernetes
manifests, Helm, shell, Python, Go, ...) directly in the reply. Unlike
`answer-technical-question`, this task is not grounded in documentation: it
declares no tool and no knowledge domain, on purpose.
