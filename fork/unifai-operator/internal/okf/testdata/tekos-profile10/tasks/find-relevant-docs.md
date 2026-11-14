---
okf_version: "0.2"
type: task
title: Find relevant documentation
description: List the Confluence pages, documentation sections and Drive files relevant to a topic, without composing an answer.
resource: https://github.com/startxfr/zuno-demo-agents/blob/main/agents/tekos/tasks/find-relevant-docs.md
stale_after: "2027-05-15T00:00:00Z"
zuno:
  profile: "1.0"
  allowed_tools:
    - search_confluence
    # The consultant's own Drive files are part of the material to scan
    # before a customer call (read only; already allowed to Tekos through
    # check-my-drive-docs, so the agent's tool union is unchanged).
    - list_drive_files
  allowed_knowledge:
    - knowledge.tech
  # The model roles this task prefers, in order, matching its entry in
  # policies/model-routing/model-routing-policy.yaml; the routing policy
  # stays the authority.
  models:
    preferred:
      - default
      - specialized
      - quality
      - reasoning
      - reasoning-external
  # Example prompts a user interface can offer for this task. Display only: choosing one does not select the task.
  prompt_examples:
    - "Find the Confluence pages describing the satellite build architecture."
    - "Which documentation covers OpenShift AI model serving?"
    - "List the reference material we have on Keycloak realm configuration."
    - "Which of my Drive files cover the customer's OpenShift upgrade?"
---

# Find relevant documentation

Given a topic or keyword, return the most relevant internal Confluence
pages, indexed documentation sections (`knowledge.tech`) and the
consultant's own Drive files, without composing a full narrative answer: a
lookup for consultants scanning the available material before a customer
call. `search_confluence` finds the Confluence pages and `list_drive_files`
lists the Drive files.
