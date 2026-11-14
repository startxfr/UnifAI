---
okf_version: "0.2"
type: tool
title: Git repository list
resource: https://github.com/startxfr/zuno-demo-agents/blob/main/agents/tekos/tools/git.repository.list.md
stale_after: "2027-05-15T00:00:00Z"
zuno:
  profile: "1.0"
  capability: git.repository.list
  used_by_tasks:
    - answer-technical-question
  usage_notes: >-
    Takes a provider (GitHub or GitLab), an owner and the owner's type (user
    or organization); returns some of the owner's public repositories, the
    most starred and the most recently active. answer-technical-question
    uses it to find the repository to read with git.repository.read.
  known_limitations:
    - "Public repositories only; private and internal ones are filtered out."
    - "Returns a short selection, not the owner's full repository list."
    - "Data classification C2 (min_classification); no external_model_policy restriction."
    - "Allowed groups: consultant, board, cdp."
    - "Access: read."
---

# Git repository list

Lists an owner's public GitHub or GitLab repositories, the first step
before `git.repository.read`.

This note grants nothing: the task's `allowed_tools` and
`policies/tools/tool-policy.yaml` decide.
