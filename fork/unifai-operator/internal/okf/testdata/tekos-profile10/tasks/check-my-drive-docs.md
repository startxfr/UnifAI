---
okf_version: "0.2"
type: task
title: Check my Drive documents
description: List the consultant's own Google Drive documents that are relevant to a project or topic.
resource: https://github.com/startxfr/zuno-demo-agents/blob/main/agents/tekos/tasks/check-my-drive-docs.md
stale_after: "2027-05-15T00:00:00Z"
zuno:
  profile: "1.0"
  allowed_tools:
    - list_drive_files
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
    - "List my Drive documents about the satellite run architecture."
    - "Which of my documents mention the Keycloak migration?"
---

# Check my Drive documents

List the consultant's own Google Drive documents that are relevant to a
project or topic. `list_drive_files` runs with the user's own delegated
identity (zuno-demo ADR-0014), so it lists only files the user can already
see. The task declares no knowledge domain: it answers from the file list.
